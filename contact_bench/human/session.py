"""Bridge between the runner's event loop and the local play page.

The runner awaits ``HumanSession.ask`` for every decision of the human seat.
The HTTP server thread reads ``state()`` and calls ``lookup``, ``submit`` and
``stop``.  Only the deciding seat's own observation (built by the engine's
allowlist) and post-game summaries ever leave this object; referee state,
other seats' private histories and audit fields are never exposed.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from ..engine.game import DecisionSpec
from .agent import HumanStopped, precheck

SEAT_LABEL = {"guesser1": "Guesser 1", "guesser2": "Guesser 2", "defender": "Defender"}


class SubmitError(ValueError):
    pass


class HumanSession:
    def __init__(self, *, run_id: str, player: str, display_name: str, model_names: dict[str, str],
                 fixtures: list, games: list, contact_dictionary, secret_dictionary=None,
                 no_progress_draws: bool = True):
        self.run_id = run_id
        self.player = player
        self.display_name = display_name
        self.model_names = model_names
        self.contact_dictionary = contact_dictionary
        self.secret_dictionary = secret_dictionary or contact_dictionary
        self.no_progress_draws = no_progress_draws
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._current: dict | None = None
        self._results: dict[str, dict] = {}
        self._fixtures = [f for f in fixtures]
        self._game_specs = {g.game_id: g for g in games}
        self.stopped = False
        self.finished = False
        self.message: str | None = None
        self.version = 0

    # ------------------------------------------------------------ runner side
    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _role(self, g) -> dict:
        if g.attacker == self.player:
            return {"role": "attack", "you": "Guesser 1", "opponent": g.defender,
                    "teammate": g.attacker_g2 or g.attacker}
        return {"role": "defend", "you": "Defender", "opponent": g.attacker, "teammate": None}

    def game_started(self, g) -> None:
        with self._lock:
            self._game_specs[g.game_id] = g
            self._current = {"game_id": g.game_id, "fixture_id": g.fixture_id, "leg": g.leg, **self._role(g)}
            self.version += 1

    def game_finished(self, g, rec: dict) -> None:
        if rec.get("run_status") != "complete":
            return
        s, sc = rec["summary"], rec.get("score") or {}
        base = (sc.get("baseline") or {})
        with self._lock:
            self._results[g.game_id] = {
                "game_id": g.game_id, "fixture_id": g.fixture_id, "leg": g.leg, **self._role(g),
                "secret": s["secret"], "outcome": s["outcome_status"], "terminal_reason": s["terminal_reason"],
                "turns_used": s["turns_used"], "turn_limit": s["turn_limit"],
                "initial_prefix": s["initial_prefix"], "final_prefix": s["final_prefix"],
                "cost": sc.get("cost"), "reference_cost": base.get("value"),
                "public_history": rec.get("public_history", []),
            }
            self.version += 1

    def preload(self, records: list[dict]) -> None:
        """Results of games completed in earlier sessions of this run."""
        for rec in records:
            g = self._game_specs.get(rec["game"]["game_id"])
            if g is not None:
                self.game_finished(g, rec)

    async def ask(self, spec: DecisionSpec, decision_id: str, *, game, max_lookups: int) -> tuple[Any, dict]:
        if self.stopped:
            raise HumanStopped("stopped")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        started = time.time()
        entry = {
            "decision_id": decision_id, "spec": spec, "future": fut, "started": started,
            "max_lookups": max_lookups, "lookups": [], "lookup_results": [], "rejected": 0,
        }
        with self._lock:
            self._pending = entry
            self.version += 1
        try:
            action = await fut
        finally:
            with self._lock:
                if self._pending is entry:
                    self._pending = None
                self.version += 1
        if action is _STOP:
            raise HumanStopped("stopped")
        meta = {"think_seconds": round(time.time() - started, 3), "lookups": entry["lookups"],
                "prechecks_rejected": entry["rejected"]}
        return action, meta

    # ------------------------------------------------------------ server side
    def _resolve(self, fut: asyncio.Future, value: Any) -> None:
        def set_():
            if not fut.done():
                fut.set_result(value)
        if self.loop is None:
            raise RuntimeError("session not attached to an event loop")
        self.loop.call_soon_threadsafe(set_)

    def _require_pending(self, decision_id: str) -> dict:
        p = self._pending
        if p is None or p["decision_id"] != decision_id:
            raise SubmitError("that decision is no longer pending; reload the page")
        return p

    def lookup(self, decision_id: str, name: str, args: Any) -> dict:
        with self._lock:
            p = self._require_pending(decision_id)
            if len(p["lookups"]) >= p["max_lookups"]:
                raise SubmitError(f"lookup limit reached ({p['max_lookups']} per decision)")
            out = self.contact_dictionary.execute(name, args)
            p["lookups"].append({"name": name, "args": args})
            entry = {"name": name, "args": args, **out}
            p["lookup_results"].append(entry)
            self.version += 1
            return {**entry, "remaining": p["max_lookups"] - len(p["lookups"])}

    def check(self, decision_id: str, action: Any) -> str | None:
        with self._lock:
            p = self._require_pending(decision_id)
            spec = p["spec"]
        return precheck(spec, action, contact_dictionary=self.contact_dictionary,
                        secret_dictionary=self.secret_dictionary)

    def submit(self, decision_id: str, action: Any, *, force: bool = False) -> dict:
        """Hand the action to the engine.  Unless ``force``, an action the engine
        would reject is returned to the page with the reason instead."""
        reason = self.check(decision_id, action)
        with self._lock:
            p = self._require_pending(decision_id)
            if reason and not force:
                p["rejected"] += 1
                return {"accepted": False, "reason": reason}
            self._pending = None
            self.version += 1
        self._resolve(p["future"], action)
        return {"accepted": True, "engine_will_reject": bool(reason), "reason": reason}

    def stop(self) -> None:
        with self._lock:
            self.stopped = True
            p, self._pending = self._pending, None
            self.version += 1
        if p is not None:
            self._resolve(p["future"], _STOP)

    def mark_finished(self) -> None:
        with self._lock:
            self.finished = True
            self.version += 1

    def mark_paused(self, message: str) -> None:
        """The runner stopped with games still pending (budget, provider halt)."""
        with self._lock:
            self.stopped = True
            self.message = message
            self.version += 1

    def _fixture_rows(self) -> list[dict]:
        rows = []
        for f in self._fixtures:
            ab, ba = self._results.get(f.game_ab), self._results.get(f.game_ba)
            row = {"fixture_id": f.fixture_id, "opponent": f.model_b, "attack": ab, "defend": ba,
                   "points": None, "draw": False}
            if ab and ba and ab["cost"] is not None and ba["cost"] is not None:
                np_ab = ab["outcome"] == "capped" and ab["final_prefix"] == ab["initial_prefix"]
                np_ba = ba["outcome"] == "capped" and ba["final_prefix"] == ba["initial_prefix"]
                if self.no_progress_draws and np_ab and np_ba:
                    row["points"], row["draw"] = 0.5, True
                else:
                    row["points"] = 1.0 if ab["cost"] < ba["cost"] else 0.5 if ab["cost"] == ba["cost"] else 0.0
            rows.append(row)
        return rows

    def state(self) -> dict:
        with self._lock:
            p = self._pending
            pending = None
            if p is not None:
                spec: DecisionSpec = p["spec"]
                pending = {
                    "decision_id": p["decision_id"], "seat": spec.seat, "seat_label": SEAT_LABEL[spec.seat],
                    "phase": spec.phase, "observation": spec.observation,
                    "lookups_remaining": p["max_lookups"] - len(p["lookups"]),
                    "max_lookups": p["max_lookups"], "lookup_results": list(p["lookup_results"]),
                }
            fx = self._fixture_rows()
            done = [r for r in fx if r["points"] is not None]
            return {
                "version": self.version,
                "run_id": self.run_id,
                "player": self.player,
                "display_name": self.display_name,
                "model_names": self.model_names,
                "status": ("stopped" if self.stopped else "finished" if self.finished
                           else "your_turn" if pending else "waiting"),
                "message": self.message,
                "current": self._current,
                "pending": pending,
                "fixtures": fx,
                "summary": {"fixtures": len(fx), "complete": len(done),
                            "points": sum(r["points"] for r in done)},
            }


_STOP = object()
