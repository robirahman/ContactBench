# Contact Benchmark: Research and Release Checklist

**Status:** version 0.4 project plan with confirmed game clarifications and proposed benchmark settings; no implementation, model results, or publication claimed.  
**Companion:** the Codex implementation specification is the authority for the executable rules. Resolve any mismatch before a scored run.  
**Official API and arXiv guidance checked:** 2026-11-16. Recheck before implementation and submission.

This repository checklist covers scientific framing, engineering, experiments, paper, reproducible release, leaderboard, and maintenance.

## Ownership and completion rules

- **Researcher:** owns scientific questions, rule approval, dataset rights, spending decisions, model selection, interpretation, authorship, submission, and publication.
- **Codex:** implements the approved protocol, tests, adapters, analysis tools, documentation, and website artifacts. It can prepare a release or submission bundle; it does not establish novelty or scientific validity by implementing code.
- **Joint:** researcher reviews the evidence and signs off on each stage gate. Link completed checkboxes to supporting artifacts where practical.

No live model calls are authorized by this document alone. The researcher will provide credentials through their own environment and explicitly start budgeted runs. Never put keys in this repository, transcripts, exported data, or website assets.

## Scientific commitments to preserve

Guesser 1 remains the cluegiver and Guesser 2 remains the receiver throughout a game. Both words are privately committed before the defender's full blocklist is published. Under the researcher's latest clarification, if both committed words are blocked, neither commitment identity is disclosed. If exactly one is blocked, the unblocked guesser chooses whether to reveal that already committed word or cancel the contact attempt. A blocked word has already been publicly emitted in the blocklist, so withholding its attribution does not preserve the word. A canceled, unblocked word remains available for a future contact only if it has not otherwise appeared publicly, including in the clue or as a complete displayed prefix that is a legal dictionary word. Keep each seat's own private history isolated from the other seats.

**Confirmed winning conditions:** a literal clue mention, blocklist entry, direct guess, or actually revealed guess wins if it equals the secret. A sealed commitment is analogous to silently thinking a word: it neither wins nor tests that word against the target, and continuing play does not privately establish that it was wrong. The earlier private-registration-hit interpretation was an assistant misunderstanding, not an alternative requested by the researcher. A successful unblocked contact also wins immediately when the next actual letter completes the secret; no extra END symbol or subsequent spoken guess is required.

Maintain one public appeared-word set U. It includes admitted public gameplay words and every complete displayed prefix that exactly equals a word in the legal vocabularies, both at initialization and after an earned letter. Remove appeared words from both possible secrets and future contact words; never prune from a hidden commitment. Admit registrations against the pre-turn contact list, but award contact only on a matching, unblocked, opened word that was not also publicly named in the current clue. Its simultaneous paired revelations constitute the contact declaration and do not disqualify themselves. A word literally spelled out in the clue can win if it is the secret, but cannot subsequently earn a contact letter on that turn. Exactly one blocked guess implies that the two words differ, so the optional reveal cannot earn a contact letter. Admit bounded, well-formed outputs before checking for target mentions; rejected dictionary dumps do not win or become public communication.

**Displayed dictionary-valued prefixes count as appeared words.** At a round boundary, C_secret is the words in V_secret that start with p minus U, and C_contact is the words in V_contact that start with p minus U. These sets coincide when the vocabularies coincide. If p itself is a legal word, it has already entered U: after reaching `art` without winning, `art` is both excluded as the target and ineligible for future contact, while `artist` can remain available. In a valid ongoing state all remaining matching words are consequently strictly longer than p. Match only the complete displayed prefix; displaying `artist` does not separately emit its substring `art`. Do not scan the input dictionary, schemas or private records as public appearances. Require the initial prefix to be strictly shorter than every sampled secret, with target support and baseline denominators reflecting initialization exclusions. A contact completing the secret is recorded as prefix_completed, not as a player-guess utterance.

**Other proposed benchmark defaults, to review before freezing:** collect both initial responder commitments without conditioning requests on hidden words; publish the blocklist, then collect an extra reveal/cancel decision when required within the same game turn. Give that unblocked seat its own word, the blocklist, and the private fact that its partner was blocked, without naming the partner's word. The defender-visible live history contains the clue, full blocklist, actually opened role-labeled guesses, prefix/outcome without a hidden-branch explanation, and public used words. Do not publish blocked-seat flags, a both-blocked label, hidden match/coverage, a reveal/cancel decision or its actor, or a withheld commitment identity. If Guesser 2 passes, provisionally reveal Guesser 1's word if unblocked and otherwise withhold it, without a new choice. A model-invalid reveal/cancel response provisionally becomes cancel; an infrastructure-missing response stays unresolved. Retain Guesser 1's optional direct action, which skips responders. These visibility and pass choices remain proposals.

**Character-only primary profile:** limit the clue's complete decoded text to a configurable C characters, with no separate live-candidate mention cap. C=100 is a proposed initial setting based on the researcher's example, not a mandated rule; development can compare C=100 and C=240 before freezing the main condition. Retain the proposed maximum word length 20. The assistant's earlier k=4 restriction is removed from the primary profile; any such restriction is a separate legacy/ablation condition. Listing legal whole words in clues is permitted and must be represented by an explicit baseline.

**Enumeration suite:** retain first/last two-guess search, add alphabetical and reverse clue-only whole-word enumeration, and include full-capacity packing that uses the two registered/revealed guesses as well as the clue. For each full-capacity batch, place the two longest selected words in the free guess slots and the remaining selected words in a space-separated clue; always reveal when offered cancellation. Use fixed tie rules and pre-turn legality. Clue-only controls must avoid accidentally selecting new candidates in the two guess slots. Audit the emitted sequence and exact character count. For clue-only output, total dictionary characters divided by C is not generally a strict turn bound because whole words leave unused space. For combined maximal-prefix packing, the two extra guesses support the proved bound min(ceil(n/2), ceil((sum word lengths+n)/(C+1))). If D includes one separator between words, this is at most ceil(D/C); D=1,000,000 and C=100 gives a combined bound of 9,901 turns. Do not apply that combined guarantee to the weaker clue-only policy or ignore separator overhead.

**Primary completion reference:** use the specified memoryless random packing policy, with an empty-blocklist defender and always-reveal. At each turn, freshly shuffle all remaining public target candidates uniformly, take the longest consecutive prefix of that ordering that fits in the clue plus two free guess slots, emit that batch, remove it and repeat with a fresh shuffle. For feasibility, assign the two longest words in the selected batch to the guess slots and put the rest in the clue. The policy does not know the secret or its length. Fresh shuffling makes the same policy applicable after a model-play cap, avoiding a change from a partially remembered ordering to a new fallback policy.

Let R(S,s) be the true expected completion turns of that reference from public candidate set S when the secret is s. Under this label-independent policy it depends on the candidate word-length histogram and the secret's length, not its alphabetic rank. It remains an objectively specified expectation over a scripted legal policy; no participating LLM supplies the reference.

For initial candidate set S_initial, final unresolved candidate set S_final, cap L and winning turn t, use

\[
B_g=R(S_{\mathrm{initial},g},s_g),\qquad
C_g=\begin{cases}t_g&\text{if solved within the limit},\\L+R(S_{\mathrm{final},g},s_g)&\text{if unresolved at the cap}.\end{cases}
\]

For general mixed-length states, estimate R by complete scripted enumeration rollouts, recording every word's emission turn and averaging within each word-length class, then across rollouts. The scorer can use the secret's length to select its answer-key estimate; that information never enters the enumeration policy or players' observations. Seed rollouts from the versioned word-length histogram and packing configuration without conditioning the policy on the actual secret or alphabetical word identities. Keep scorer randomness private until the release policy permits disclosure. Store rollout means as exact rational numbers, while clearly distinguishing exact arithmetic from numerical accuracy of the estimated expectation. Report Monte Carlo standard errors separately from experimental uncertainty, treating complete rollouts as sampling units rather than independent word ranks.

Freeze rollout count, seeds, algorithm and cache keys before final analysis. Proposed starting counts are 2,048 rollouts for development and 4,096 for final scoring, subject to a prespecified precision and ranking-stability check. For equal-length words of length ell, the reference reduces exactly to the fixed width b=2+floor((C+1)/(ell+1)), capped by the remaining candidate count, and

\[
F_b(n)=\frac{1}{n}\sum_{r=1}^{n}\left\lceil\frac rb\right\rceil.
\]

Use exact evaluation when all candidates fit in one turn, for the equal-length formula, and for tiny exhaustive fixtures. The general character-only reference is not the old count-only F_b(n) formula. Averaging only alphabetical and reverse enumeration is not generally target-neutral. The fallback uses the public prefix and appeared-word set, including dictionary-valued prefix displays; it cannot exploit hidden commitments or forecasts.

**Required first-and-last baseline:** Guesser 1 selects the alphabetically first live completion and Guesser 2 selects the last, without naming extra live candidates in the clue, and the unblocked player always reveals if offered a choice. Every selected endpoint is then either publicly blocked or publicly revealed. This guarantees success within ceil(n/2) rounds against any defender; extra blocks can only speed this enumeration or themselves hit the secret. With an empty blocklist and no additional eliminations, its uniform-target uncapped mean is F_2(n). For even n this is (n+2)/4, and for odd n it is (n+1)^2/(4n). With n=100, the mean is 25.5 rounds and the worst case is 50. The same mean holds with a cap followed by the same two-guess resolver; substituting the stronger character-packing fallback defines a different hybrid cost. Keep this baseline visible, score its model-stage play with the condition's common primary fallback, and label its standalone F_2 property separately. Deduplicate the singleton endpoint and explicitly handle the terminal winning condition.

**Primary scientific efficiency:** aggregate speedup S=sum_g B_g/sum_g C_g, equivalently the ratio of mean completion costs. Higher is better for attack efficiency. This is not the arithmetic mean of individual B_g/C_g. Define the weighting and opponent panel before comparing models. The same fresh-shuffle reference used before and after a cap has equal ideal expected cost, giving unit population speedup when compared with itself. This is an expectation statement; finite reference games, empirical ratios and Monte Carlo estimates need not equal one.

**Complementary competition:** on each secret, run A+A attacking B and B+B attacking A with fresh contexts. Compare effective costs under the frozen scoring policy and fit the preregistered Elo-style rating. Mixed-length unresolved costs can contain Monte Carlo error, so prespecify precision, comparison and sensitivity handling. Exact rational comparison of estimated means does not prove the ideal expectations are ordered correctly. Do not invent draws by arbitrary overlap of Monte Carlo intervals; use the declared policy and report stability as scoring precision increases. Keep ratings separate from efficiency, offensive/defensive diagnostics, and self-play balance. A self-play offense win rate is not a general skill score.

## Start here: recommended next tasks

- [ ] **Researcher:** review the implementation specification, preserve the confirmed spoken-word and final-letter winning rules, and freeze the remaining choices affecting visibility, turn costs, character budgets and scoring.
- [ ] **Researcher:** select a legally redistributable lexicon and identify a small development-only target set.
- [ ] **Codex:** implement the deterministic engine, replay, scorer, and scripted baselines before provider adapters.
- [ ] **Joint:** validate toy games, literal packing schedules, exact small-state reference expectations and Monte Carlo precision, then run a small, capped pilot after the researcher authorizes it.
- [ ] **Researcher:** use pilot evidence to decide whether the task has sufficient difficulty, variation, and interpretability to justify a full study.

## Phase 1 — Establish the scientific question and prior art

**Lead: Researcher. Codex assists with an evidence table and bibliography.**

- [ ] Write the proposed construct: useful coordination under asymmetric information, clue interpretation, blocking, search efficiency, or some explicitly stated combination. Distinguish these from vocabulary size and obedience to output schemas.
- [ ] State the contribution provisionally: an executable Contact variant, an objective scoring method, an evaluation protocol, and empirical findings if supported. Do not claim the first Contact benchmark without a completed prior-art review.
- [ ] Review Moskvichev and Steyvers, [Word Games as Milestones for NLP Research](https://mstrep.s3.amazonaws.com/publications/GAMNLP-2019_paper_9.pdf), a position paper that discusses Contact. Determine precisely how the proposed benchmark differs.
- [ ] Investigate the [Daniel Tan / Cameron Tice discussion](https://www.lesswrong.com/posts/4mtqQKvmHpQJ4dgj7/daniel-tan-s-shortform?commentId=747BwDjDxX7CERayP) and [llm-contact repository](https://github.com/camtice/llm-contact), and [Nikita Fomin's AI Contact Game](https://www.linkedin.com/pulse/ai-contact-game-nikita-fomin-jzqqe) and [repository](https://github.com/fomin-n/ai-contact-game). These are known leads; their code has not been audited for this checklist. Record implemented rules, evaluation methods, dates, licenses, and overlap after inspection.
- [ ] Compare with related [Codenames evaluation](https://arxiv.org/abs/2412.11373), [Other-Play](https://proceedings.mlr.press/v119/hu20a.html), [clembench](https://arxiv.org/abs/2406.14051), and [work on steganography](https://arxiv.org/abs/2507.02737). Verify which claims each source supports; do not treat all as equivalent tasks.
- [ ] Identify likely confounds and falsifiable questions: better clue coordination, better defense, dictionary ordering, prior knowledge of frequent words, invalid-action rates, or greater inference expenditure.

**Gate 1:** a one-page research statement and comparison table explain the contribution without depending on an unverified novelty claim.

## Phase 2 — Freeze the executable game

**Lead: Researcher. Codex converts decisions into a state-transition table.**

- [ ] Approve fixed Guesser 1 and Guesser 2 roles, target selection, initial prefix, optional direct guesses, sealed commitments, unrestricted finite defender blocklists, and exact whole-word target detection. Record which parameters are proposed benchmark restrictions.
- [ ] Freeze what counts as one attack turn. The optional post-block reveal/cancel decision is part of the current turn, including turn L. A clue round uses up to four decisions, while a direct guess uses one; report API expenditure separately from game turns.
- [ ] Implement the confirmed winning conditions: only public target utterances test guesses, and a contact revealing the final actual letter wins immediately. Remove the assistant's former private-registration-hit interpretation and END-symbol requirement from active rules and prompts.
- [ ] Implement public appearance and retirement precisely: publish the full blocklist; hide both commitment identities when both are blocked; offer only the unblocked seat a reveal/cancel choice when exactly one is blocked; provisionally reveal both simultaneously when neither is blocked. Remove public gameplay words and complete dictionary-valued prefix displays from candidate secrets and future contacts. Hidden canceled commitments alone cause neither public pruning nor retirement.
- [ ] Apply target-utterance precedence when a valid public emission occurs, before ordinary contact or retirement. A revealed guess can win despite mismatch; a canceled secret commitment does not win or privately test the word. A defender block containing the secret wins for offense. Otherwise, a successful contact reveals one actual letter and wins if it completes the target. Rejected raw output is not an admitted utterance.
- [ ] Resolve boundary cases: a contact involving the secret, attempted defense using the secret, both-blocked mismatches, one-blocked cancellation by either seat, a canceled word also mentioned in the clue, completion on the last permitted turn, a singleton candidate set, repeated guesses, invalid words and passes. Require an initial prefix shorter than the target. Review the provisional pass rule and choose a secret-independent default for a model-invalid reveal/cancel decision.
- [ ] Freeze the clue character budget, lexical tokenization, separator convention and allowed encoding strategies. The primary character-only profile has no separate live-candidate mention cap; C=100 is a proposed starting point, with C=240 a development comparison. Verify that whole-word packing uses all permitted clue and guess channels without splitting target words across turns. Separate any human semantic-clue audit from automatic scoring.
- [ ] Add every complete displayed prefix that exactly equals a legal dictionary word to used_words, at initialization and after an earned letter. Derive both target and contact lists by prefix filtering minus used_words; equal vocabularies give equal boundary sets. Test that displaying `art` eliminates and retires it, and that displaying a longer string does not separately retire every dictionary substring. Do not confuse these public appearances with hidden commitments or scan the full input dictionary as gameplay.
- [ ] Approve a phase-specific visibility matrix for the secret, commitments, clue, full blocklist, private cancellation observation, public history, and audit logs. Ensure response ordering cannot expose one player's answer before commitment. Keep blocked-seat flags, both-blocked labels, hidden match/coverage, reveal/cancel decisions and actors, and withheld identities out of defender-visible live history. Retain each seat's own private history without sharing it with its partner. Test a singleton blocklist to catch identity leaks through branch labels.
- [ ] Specify refusal, malformed output, timeout, and infrastructure-failure treatment. Keep outcome_status separate from collection_status: established public target-utterance or prefix-completion evidence fixes cost t even if an irrelevant diagnostic response is unavailable; an unresolved cost remains unscoreable until recovered. Invalid model responses use their canonical game penalty.
- [ ] Demonstrate why unlimited blocking is not a free defensive win: blocking every remaining candidate except the secret reveals it by complement. Measure the information cost of blocks against the public emissions that actually occur; a withheld commitment is not automatically public. Blocking a word already named in the clue adds no further elimination, while blocking a hidden intended word can disclose a fresh negative.

**Gate 2:** two readers can resolve the same toy transcript identically without asking an LLM to judge it. Hash the approved protocol and prompts.

## Phase 3 — Build and document the lexicon and target distribution

**Lead: Researcher for rights and distribution; Codex for processing.**

- [ ] Record lexicon provenance, version, license, redistribution permission, attribution requirements, and every transformation.
- [ ] Freeze normalization, character set, casing, minimum/maximum length, inflections, compounds, proper nouns, and exclusions. Check for duplicates after normalization.
- [ ] Define legal contact words and legal targets explicitly. If the vocabularies differ, publish both sets. Both use the same public appeared-word set, which includes complete dictionary-valued prefix displays; equal vocabularies give equal boundary candidate lists. Ensure target support, sampling and initial/final reference states incorporate initialization exclusions and displayed-prefix retirement.
- [ ] Choose target sampling and prefix strata. Prefer a transparent primary distribution; if using frequency weighting, document the consequences for the brute-force reference and add an informed guessing baseline.
- [ ] Separate development, calibration, and final evaluation manifests and transcripts. The default uses independent draws from the same declared target distribution, so words may overlap. If choosing disjoint word or lexical-family supports, declare each split's legal target support and compute candidate counts from it; do not preserve a larger denominator while claiming the full-support uniform baseline theorem.
- [ ] Record target-selection seeds and hashes privately until the release policy permits disclosure. Decide how fresh leaderboard targets will be generated without silently changing difficulty.
- [ ] Inspect candidate-count, word-length histogram and prefix-depth distributions. Record all-in-one-turn packing cases and full-prefix initialization exclusions; remove trivial cases only through documented rules established before final evaluation.

**Gate 3:** a reproducible dataset manifest rebuilds the exact dictionary and partitions, with clear rights to distribute every released asset.

## Phase 4 — Implement the benchmark and provider adapters

**Lead: Codex. Researcher reviews protocol fidelity.**

- [ ] Build a pure game engine, phase- and role-filtered observations, admission-before-broadcast validation, conditional reveal/cancel and final-letter completion transitions, event logs, deterministic replay, and independent baseline agents. Reveal must open the existing commitment and cannot supply a replacement word or extra clue.
- [ ] Implement the character-packing reference and scorer independently of model providers: exact all-fit/equal-length/tiny-state cases, reproducible mixed-length Monte Carlo rollouts, length-class averaging, complete-rollout standard errors, exact rational storage of sampled means, and versioned histogram/configuration caches. Retain the two-guess and clue-only controls.
- [ ] Implement paired match scheduling, role swapping, explicit seeds, resumable runs, atomic checkpoints, and a configuration manifest covering every result-affecting choice.
- [ ] Implement OpenAI, Claude, and Gemini adapters behind one typed interface. Pin SDK versions and make provider/API-family/model selection explicit.
- [ ] Validate supported model settings; never silently drop requested parameters. Record effective API version, reasoning configuration, output limit, schema mode, and any provider model identifier.
- [ ] Use independent histories for every seat and game. Preserve each seat's own unrevealed commitments and decisions, but do not place them in another seat's history or in public candidate filtering. Keep provider conversation IDs, caches, private commitments, and target data from crossing authorized boundaries.
- [ ] Preserve raw provider usage and normalized nullable fields for input/output/total/cached/reasoning tokens, finish reason, request ID, latency, retries, and errors. Avoid double-counting reasoning tokens.
- [ ] Implement bounded transient-error retries, quota-aware scheduling, spend caps, operational cancellation, and resume without applying a successful action twice. Give decisions phase-specific IDs because the same seat may commit and later choose reveal/cancel in one turn. Persist the published blocklist and pending choice without resampling earlier decisions. Account for SDK retries as well as application retries.
- [ ] Produce analysis exports, a dataset card, command-line documentation, example configurations without secrets, and a public export that excludes keys and unreleased target material.

**Gate 4:** the offline system runs complete tournaments using scripted agents and reproduces its own scores from logs alone.

## Phase 5 — Verify correctness before paid experiments

**Lead: Codex; joint review of evidence.**

- [ ] Test all consequential state transitions and information boundaries, including both-blocked hiding, both orientations of one-blocked reveal/cancel, neither-blocked simultaneous opening, passes, contact resolution, prefix changes, malformed actions, and termination. Verify immediate final-letter victory with no END symbol, including on turn L. Canceled unmentioned words remain eligible only as allowed by public rules; words in the clue, blocklist or complete dictionary-valued prefix displays do not.
- [ ] Exhaustively enumerate tiny mixed-length states and fresh-shuffle outcomes to verify R(S,s), whole-word packing, candidate preservation, rational storage, aggregate scores and paired comparisons. Verify equal-length reduction to F_b(n) with b=2+floor((C+1)/(ell+1)), and exact one-turn cost when all candidates fit. Include counterexamples to simple total-characters/C ceilings and to alphabet/reverse averaging as a generally target-neutral fallback.
- [ ] Verify cap consistency for the same fresh-shuffle reference used both before and after the cap, with an empty-blocklist defender. Its ideal expected cost equals B; finite games, empirical ratios and Monte Carlo estimates have sampling error. Check first/last separately: n=100 has empty-defender mean 25.5 and worst-case guarantee 50 with always-reveal, including against nonempty blocklists. Do not assign its standalone F_2 mean to a hybrid using the stronger packing fallback.
- [ ] Validate mixed-length Monte Carlo estimates against tiny exact cases and independent seeds. Check within-length exchangeability, correct whole-rollout standard errors, secret-independent policy seeds, cache equivalence and increasing-rollout convergence. Distinguish exact arithmetic on estimates from exact evaluation of R; require the predeclared precision/stability gate before final scoring.
- [ ] Test target hits in every public gameplay channel, including either revealed guess during a mismatch, clue mentions, direct guesses and defender blocks. A canceled secret commitment must not win or be excluded merely because it was registered. Verify that a displayed `art` is both excluded as a target and retired for contact, including when it is the initial prefix; a longer displayed prefix does not separately emit dictionary substrings. A final earned prefix equal to the secret wins with terminal reason prefix_completed. Verify no player-utterance hit from dictionary inputs, schemas, private reports or rejected oversized output, while retaining the explicit prefix-display retirement rule.
- [ ] Test current-clue freshness separately from registration legality: registering a pre-turn legal word already named in that clue remains a legal guess, but even an unblocked matching pair cannot earn a letter on it. Do not count a covered match as a prevented contact if the clue had already disqualified that word, or if a public target hit had already ended the game. Simultaneous paired revelations do not disqualify their own contact.
- [ ] Confirm public logs cannot alter game state, hidden commitment identities and match flags stay hidden in withheld branches, private values cannot leak through error messages or candidate lists, and replay does not require provider access. Verify that full audit logs retain objective labels without leaking them into live observations.
- [ ] Fault-test an interrupted run before and after blocklist publication and during a pending reveal/cancel decision, exhausted quota, repeated response delivery, invalid JSON, refusal, and missing usage metadata. Verify retries do not grant free model decisions and infrastructure-missing choices are not silently treated as cancellations or reveals.
- [ ] **Researcher:** authorize a small live smoke test with a stated maximum number of calls and maximum spend. **Codex:** verify schema compatibility, role isolation, accounting, and one resumed game for each selected provider.

**Gate 5:** no unexplained score discrepancy, secret leak, or ambiguous retry behavior remains. Save the test report with the exact code revision.

## Phase 6 — Budget and run a development pilot

**Lead: Researcher for budget and selection; Codex for execution tools.**

- [ ] Select representative model families and reasoning settings without assuming current SOTA will be unsaturated. Record model access, documented limits, and any preview status.
- [ ] Estimate calls from actual action paths, including two role-swapped games per paired contest and the extra decision on a one-blocked round. A full M-model round robin contains M(M−1)/2 model pairings per target/repetition block. With K targets per pair and R repetitions, there are M(M−1)KR raw games and at most 4L decisions per game before retries and separate audits. For M=6, K=10, R=1, L=20, budget up to 24,000 game decisions across 300 games; actual usage depends on action paths.
- [ ] Measure prompt growth and token use on smoke tests; estimate full-run costs from observed distributions, not just a first-turn average. Include retries and incomplete games in the budget.
- [ ] Set daily and total spend caps, concurrency, quota groups, stop conditions, and monitoring. Record the dated price assumptions separately from measured token use.
- [ ] Run pilot targets across several plausible turn limits and difficulty strata. Keep all calibration results separate from confirmatory test results.
- [ ] Run first/last two-guess search, alphabetical and reverse clue-only whole-word enumeration, full-capacity packing with two longest selected words in guess slots, and the same fresh-shuffle packing policy used by the primary reference. All enumeration policies reveal when offered cancellation. Add prior-informed policies where relevant and retain one-word direct search as a weaker control. Include defenders that pass, block literal clue candidates, block the full nonsecret candidate set, or use simple predictive blocklists.
- [ ] Measure reference-scoring CPU cost, cache reuse and Monte Carlo precision separately from paid model calls. Pilot the proposed 2,048-rollout development setting, predeclare the final precision/stability criterion and increase the proposed 4,096 final rollouts if needed under that rule. Do not choose scoring precision after seeing a preferred leaderboard order.
- [ ] Inspect a stratified sample of transcripts: successes, failures, surprising scores, each provider, each role, and suspected coding strategies.

**Gate 6 — Go/no-go:** proceed only if there is reliable variance, a clear improvement over meaningful baselines for at least some settings, and enough headroom to answer the research questions. If all models saturate, nearly all fail, or cheap encodings dominate, revise the development protocol and rerun the pilot before freezing it.

## Phase 7 — Validate what the benchmark measures

**Lead: Researcher; Codex supplies controlled experiments.**

- [ ] Measure solve-rate curves, effective cost, prefix progress, public candidate reduction, reveal/cancel choices, later reuse of preserved words, invalid-action rates, and inference expenditure together. Investigate disagreement between metrics.
- [ ] Ablate one-word direct guesses, first/last two-word search, clue-only dictionary enumeration, full-capacity character packing, and contact-enabled play. Compare always-reveal, always-cancel-when-permitted, and model-selected continuations. Sweep character budgets, dictionary access, turn limits, blocklist behavior and reasoning budgets. Any restored distinct-candidate cap is a separate ablation with its own legal baseline; do not reintroduce private-registration wins as an unresolved main rule.
- [ ] Separate offense and defense. The ordinary round robin gives each entrant all other models as opponents, so list each actual opponent set. For a controlled common-panel comparison, evaluate every entrant against every panel member, including diagonal self-play where necessary. Treat self-play role balance as a diagnostic, not a general skill score.
- [ ] Test heterogeneous attacker partners on a secondary track if claims extend to general cooperation. Homogeneous teammates can share conventions that do not transfer.
- [ ] Investigate dictionary-index encodings, lexical priors, memorized conventions, and opponent-specific exploitation. Decide which behaviors the benchmark should reward and state the resulting scope.
- [ ] If studying probabilities, start with a frozen-clue shadow audit on a common item bank. Obtain receiver and defender distributions over Guesser 1's intended word without changing the scored live game. The referee retains this ground truth even when the word is blocked or canceled and never revealed to players. Use all prespecified complete items rather than selecting only revealed guesses. Keep live probability telemetry off by default; enabling it defines a separate condition because elicitation can change behavior and expenditure.
- [ ] Implement and validate the optional forecast representation: top 20 distinct words plus a total tail mass spread uniformly over the remaining declared support. Use the higher-is-better quadratic score S(q,w)=2q(w)-sum_v q(v)^2. Check normalization, support, duplicate labels, tail reconstruction, and exact zero-mass cases; do not equate self-reported probabilities with internal model logits.
- [ ] Compare receiver and defender prediction on identical frozen items. Evaluate cluegivers on fixed public states and assigned intended words against a fixed receiver/defender panel. Keep decoder accuracy, predictive calibration, selective communication, and game strategy as distinct results.
- [ ] Optionally forecast the joint receiver-match event or receiver answer, as specified in the implementation document. The commitment-level match label remains available privately when the words are withheld and is distinct from an actual unblocked contact or later reveal. The primary commitment-match label includes model-invalid receiver outputs as NO_MATCH because the game treats them as pass; infrastructure-missing outcomes are unknown. A valid-receiver-only or publicly-revealed-only subset is descriptive and cannot be presented as the unconditional proper-score evaluation.
- [ ] If adding human evaluation, define its purpose, recruitment, consent, workload, and analysis before collecting data. Human participation is optional; it is not needed to make the core score objective.

**Gate 7:** the paper's intended claims survive the ablations, or have been narrowed to match the evidence.

## Phase 8 — Freeze the confirmatory experiment

**Lead: Researcher. Codex writes the machine-readable run plan.**

- [ ] Freeze protocol version, confirmed public-utterance/final-letter winning conditions, disclosure/cancellation table, private branch metadata and observer visibility, pass and invalid-choice behavior, lexicon, prompts, model configurations, target distribution, sampling weights, turn limit, fixed roles, clue character budget, exact packing policies and baseline continuation rules. Freeze reference algorithm/version, rollout count, seeds, histogram cache keys, exact-case shortcuts, precision thresholds, stability checks and code revision. Freeze probability-audit settings and live telemetry separately.
- [ ] Designate aggregate speedup as the primary efficiency statistic and paired cost-based Elo as the complementary competition summary. Specify the reference opponent panel and how new models will later be added.
- [ ] Define rating fitting, scale/anchor, draws, regularization, uncertainty and treatment of disconnected schedules. Prespecify comparison of Monte Carlo-estimated capped costs, exact ties of the frozen estimates and sensitivity to scoring noise. Do not automatically call a draw when arbitrary Monte Carlo intervals overlap. Prefer a batch fit for the published snapshot; record any separate online Elo update policy.
- [ ] Use pilot variability to choose sample size for a meaningful confidence-interval width or detectable effect. Keep the main run balanced in tasks and repetitions across pairs; put extra repeats on selected tasks in a separate diagnostic condition. Preserve pairing and clustering by target in resampling; repeated legs or stochastic repeats are not independent new words.
- [ ] Prespecify exclusions, infrastructure reruns, missing-data handling, multiplicity, exploratory analyses, and rules for judging practical equivalence. Avoid stopping when a preferred rank becomes significant.
- [ ] Reserve untouched final targets, freeze a dated analysis plan, and complete a final budget review. Public preregistration is optional; a timestamped internal plan is still valuable.

**Gate 8:** one run manifest and analysis plan fully specify the confirmatory study; no tuning on final results.

## Phase 9 — Execute and audit the final runs

**Lead: Researcher authorizes; Codex operates approved tooling.**

- [ ] Verify credential handling, available quotas, spend caps, model IDs, and the frozen manifest before starting.
- [ ] Randomize or interleave model pairings across time to reduce confounding by provider changes or outages. Record actual timestamps and endpoints.
- [ ] Monitor operational health and completeness using prespecified checks. Keep score-driven changes out of the frozen run.
- [ ] Reconcile expected and observed game counts, paired legs, targets, repetitions, failures, and costs. Re-run only according to the recorded failure policy.
- [ ] Replay every scored game and reproduce scores from frozen reference caches/seeds. Investigate duplicates, impossible candidate sets, word-ending exclusions, missing events, inconsistent model settings and unrecorded changes in reference precision. Preserve per-state estimator provenance and complete-rollout uncertainty.
- [ ] Freeze a read-only raw-data snapshot and a separate analysis-ready export, each with hashes and provenance.

**Gate 9:** every included score is traceable to a complete valid referee transcript or sufficient public target-utterance/prefix-completion evidence for a known win with separately flagged incomplete collection. A hidden secret commitment alone is never winning evidence. Every mixed-length reference estimate is traceable to its frozen algorithm, configuration, seeds and rollout cache. Never invent missing responses. Every exclusion has a reason.

## Phase 10 — Analyze and interpret

**Lead: Researcher; Codex produces reproducible tables and figures.**

- [ ] Report primary efficiency estimates and experimental uncertainty with the actual opponent population for each row; use the separate common-panel condition for identical-panel claims. Report reference Monte Carlo error and scoring-precision sensitivity separately, including dependence induced by shared caches. Include baseline performance, solved fraction, effective-cost distributions and resource use. Mark incomplete schedules provisional rather than presenting them as a complete balanced run.
- [ ] Publish the pairwise result matrix with the Elo-style leaderboard. Test sensitivity to opponent mix and rating assumptions; examine cycles instead of assuming one scalar captures every matchup.
- [ ] Report offense, defense, self-play, invalid actions, candidate-count and word-length strata, blocklist sizes, extra public candidate elimination by blocks, clue candidate mentions, reveal/cancel frequencies and eventual reuse of preserved words separately. Distinguish public target-utterance wins from final-letter contact wins, and private commitment matching from actual prefix awards. Keep optional probability-audit scores distinct from Elo and game efficiency; do not convert offense-favored self-play into an unsupported general skill claim.
- [ ] Bootstrap the actual aggregate statistic with the appropriate target clusters. Separately examine score and rank stability with higher reference rollout counts and independent frozen audit seeds under the predeclared policy. Show uncertainty when ranks are unstable; do not equate uncertain order with a game draw or overinterpret small Elo differences.
- [ ] Label confirmatory and exploratory analyses. Select example transcripts through a stated method rather than only choosing attractive successes.
- [ ] Explain remaining limitations: lexical distribution, finite dictionary, protocol variants, inference budgets, shared conventions, target contamination, evolving APIs, and the absence of evidence about untested settings.

**Gate 10:** an independent reader can distinguish measured findings from hypotheses and extrapolation.

## Phase 11 — Write the paper

**Lead: Researcher; Codex assists with drafting, references, and figures.**

- [ ] Draft sections for motivation/related work; executable game; objective scoring and fallback derivation; experimental protocol; results; ablations; limitations; reproducibility; and conclusion.
- [ ] Include an information-flow diagram, one resolved example game, dataset statistics, baseline comparison, uncertainty-bearing efficiency plot, pairwise matrix, and rating table where they add information.
- [ ] State explicitly that the target is sampled by the benchmark, how dictionaries are exposed, what the turn budget buys and which agents are instances of the same model. Explain public-utterance and final-letter winning conditions, when a commitment becomes a public guess, what cancellation preserves and each observer's access. Document that complete displayed dictionary-valued prefixes are appeared words and are retired from both future target guesses and contact, while final-letter victory is labeled prefix_completed rather than a player-guess utterance.
- [ ] Explain why unbounded dictionary enumeration makes eventual victory uninformative, why first/last guesses already give about n/4 expected rounds, and why character-limited clue lists raise the floor further. Derive the legal whole-word packing reference R(S,s), its memoryless cap consistency, exact special cases and mixed-length Monte Carlo estimator. State why total characters/C is not generally a strict packing bound, why alphabetical/reverse averaging is not generally neutral, and where the equal-length F_b formula still applies.
- [ ] Document the distinction between a mathematically objective score and the empirical validity of the construct it measures. Claim unsaturation only if the results demonstrate headroom.
- [ ] Verify every quotation, reference, model identifier, numerical claim, and table against source material or analysis output. Resolve authorship, acknowledgments, funding, and applicable disclosure requirements.

**Gate 11:** regenerate the paper's numerical tables and figures from the frozen analysis export; complete technical and editorial review.

## Phase 12 — Prepare a reproducible release

**Lead: Joint. Researcher approves rights and release scope.**

- [ ] Choose licenses separately for code, documentation, data, and inherited lexicon assets; preserve required notices.
- [ ] Publish installation instructions, lockfiles, configuration templates, test commands, baseline commands, and a small offline demonstration.
- [ ] Release rules, prompts, schemas, scorer, rating method, model manifests, target-generation procedure and enough transcripts/results to reproduce published conclusions under the stated disclosure policy. Include frozen reference seeds, algorithm version, rollout counts, length-histogram caches and Monte Carlo precision summaries. Distinguish seat-visible histories from full referee audit records. A post-study release of hidden commitments or scorer randomness does not authorize their inclusion in live prompts or player-view replays.
- [ ] Provide dataset and benchmark cards describing scope, splits, known weaknesses, intended uses, exclusions, and maintenance policy.
- [ ] Remove credentials, private account metadata, and unreleased target information from the public bundle. Audit website downloads as well as the repository.
- [ ] Tag the release; archive a stable snapshot and persistent identifier where feasible. Link the paper, code, data, and website to the same protocol version.

**Gate 12:** a fresh environment reproduces the published analysis without paid API access; rerunning models is a separate, documented operation.

## Phase 13 — Submit to arXiv

**Lead: Researcher. Codex prepares and checks the package.**

- [ ] Register/check the submitting account and investigate [endorsement](https://info.arxiv.org/help/endorsement.html) early, particularly for a first submission or new category.
- [ ] Follow the current [submission overview](https://info.arxiv.org/help/submit/index.html): select the appropriate category, complete metadata, and choose the distribution license with coauthor agreement.
- [ ] For LaTeX, upload the [source package](https://info.arxiv.org/help/submit_tex.html), required figures, and nonstandard dependencies. A PDF generated from TeX is not a substitute for submitting its source.
- [ ] Include necessary `.bib` files or a compatible `.bbl`; a pre-generated `.bbl` must have the main `.tex` file's basename. Check compiler and bibliography compatibility.
- [ ] Review arXiv's compiled PDF, figure placement, references, metadata, and supplementary links before completing submission. Allow time for moderation and any corrections.
- [ ] After announcement, record the identifier/version and update release links. Describe it as a preprint; arXiv posting does not itself constitute peer review.

**Gate 13:** the public paper and referenced artifacts are accessible and mutually consistent.

## Phase 14 — Publish and maintain the leaderboard

**Lead: Codex prepares static assets; Researcher reviews and publishes.**

- [ ] Generate the site from versioned result exports. Show efficiency and Elo as distinct views, with protocol version, public-utterance/final-letter winning rules, cancellation rules, evaluation date, model configuration, character budget, packing reference, reference precision, experimental uncertainty, game count and opponent coverage. Show probability-audit diagnostics separately and never pool incompatible versions, including 0.1, 0.2, 0.3 and 0.4, or different bandwidth/reference profiles.
- [ ] Include methodology, score definitions, paired matrix, baselines, cost/settings context, downloadable data, paper/code links, and a changelog. State when results are provisional.
- [ ] Explain why ratings depend on the pool and can move when new opponents enter. Preserve dated snapshots rather than presenting changed historical ranks as unchanged measurements.
- [ ] Define submission eligibility, verification requirements, rerun policy, who bears API costs, and how model aliases or provider updates produce new entries.
- [ ] Check responsive layout, keyboard access, contrast, empty/error states, sorting, ties, downloads, and rendering of uncertainty. Keep credentials and raw provider access out of the client bundle.
- [ ] Approve the concrete site build and publish it through the chosen hosting account. Check the live pages and links after deployment.
- [ ] Establish an issue/reporting channel, periodic dependency/API checks, result-correction process, and protocol versioning rules. Freeze old seasons when material rules or distributions change.

**Final gate:** readers can understand, reproduce, and challenge the results without treating a leaderboard rank as a universal measure of intelligence.

## Provider reference notes for implementation

Checked 2026-11-16; recheck support for the selected model/API version before live execution.

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [token accounting](https://developers.openai.com/api/docs/guides/token-counting), and [rate limits](https://developers.openai.com/api/docs/guides/rate-limits): handle refusals/truncation, preserve usage totals, and bound retries.
- [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) and [thinking compatibility](https://platform.claude.com/docs/en/build-with-claude/thinking): API versions and models differ in accepted settings. Do not mandate universal `temperature=0`; the current documentation describes versions rejecting sampling parameters.
- [Gemini Interactions migration](https://aistudio.google.com/docs/migrate-to-interactions), [thinking](https://aistudio.google.com/docs/thinking), and [rate limits](https://aistudio.google.com/docs/rate-limits): current guidance recommends Interactions for new work while retaining `generateContent` support. Pin the selected API family, distinguish usage fields, and schedule against project-level quotas.
