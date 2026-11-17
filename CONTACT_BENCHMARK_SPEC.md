# Contact Benchmark Implementation Specification

Version: 0.4 proposed implementation protocol  
Revised: 16 November 2026  
Audience: Codex implementing the benchmark and the researcher running the study

## 1 Purpose and implementation mandate

Build a reproducible Contact benchmark with two cooperating guessers and one defender. Guesser 1 gives a public clue and privately commits an intended word. Guesser 2 privately commits one answer. The defender submits a public blocklist of any finite size, including zero. Guess commitments are opened selectively after the blocklist: neither is opened when both are blocked; when exactly one is blocked, the unblocked player may reveal its guess or cancel and keep it hidden.

This draft incorporates the researcher's confirmed mechanics: private registration is analogous to silently thinking a word and never tests the target. A public target utterance wins, and a successful contact that earns the final actual letter also wins immediately. The previous drafts' private-registration interpretation and extra END-symbol step were assistant mistakes and are removed.

Blocked words are already public through the blocklist, even when the defender is not told which words the guessers selected. A canceled unblocked word is preserved if not independently emitted. Primary clue legality now uses a character limit without the assistant-proposed four-word cap. The new enumeration reference packs literal candidate words into that character budget and also uses both guess slots; it does not try to convey semantic clues.

The engine must grade outcomes, candidate sets, completion costs and prediction scores in ordinary code. No LLM judge or privileged reference model is needed. Other evaluated models provide opponents and teammates, not correctness judgments.

Deliver a deterministic engine, baselines, OpenAI/Anthropic/Google adapters, resumable tournament runner, reproducible scorer with exact arithmetic for recorded finite estimates, optional probability diagnostics, analysis scripts, tests, reproducible exports and a static leaderboard. The researcher supplies credentials, chooses the production lexicon and model configurations, runs paid experiments, writes the paper and publishes results.

### Changes from version 0.3

| Area | Version 0.4 draft |
|---|---|
| Private commitments | Registration is separate from public revelation |
| Both guesses blocked | Neither commitment is opened; their words are already emitted through the blocklist |
| Exactly one guess blocked | Unblocked seat privately chooses reveal or cancel; no possible contact on this branch |
| Neither guess blocked | Both commitments are opened simultaneously |
| Target hit | Confirmed: public clue, public blocklist, direct guess or actually opened guess; silent registration never wins |
| Last letter | A successful contact revealing the final letter wins immediately; no END step |
| Word preservation | A canceled word stays available only if it has not appeared in any counted channel, including as a complete displayed prefix |
| Defender feedback | No hidden guess identities, match flags, blocked-seat flags or cancellation details in live history |
| Clue bandwidth | Character limit only in the primary profile; no separate literal-candidate count cap |
| Baselines | First/last, clue-only dictionary listing, and clue-plus-two-guess packing; enumeration always reveals |
| Scoring | Expected completion of a declared random character-packing policy; word lengths matter |
| Numerical evaluation | Exact special cases/tiny fixtures; reproducible length-class-averaged Monte Carlo otherwise |
| Resources | Up to four model decisions per clue turn, including one conditional reveal/cancel decision |
| Forecast labels | Private referee commitments remain scoreable even when never publicly opened |

The first/last formula remains valid for that baseline. A fixed-b count-only formula is no longer the general character-budget scorer; it remains an exact equal-word-length special case. No implementation, model measurements or benchmark headroom is claimed by this document.

### Instructions to Codex

Implement in milestones: engine/scorer and offline tests; baselines/replay; adapters/runner; statistics and optional forecast audits; static leaderboard/release documentation. Complete an executable offline demonstration at each relevant milestone.

MUST denotes a requirement within the specified profile. User-supplied rules and additional proposed choices are separated in Section 3. Public-utterance target hits and final-letter contact wins are confirmed. Implement the remaining proposed bandwidth, reference-policy, numerical and operational choices as a configurable draft, and reject unsupported settings rather than approximating a different game.

Use fixtures for development. Paid execution must be an explicit, budgeted command. Record rule or score departures in a decision log and change the protocol version. Do not fabricate benchmark results or publish as part of implementation. See CONTACT_PROJECT_CHECKLIST.md for research and publication tasks.

## 2 Measurement goals

The main efficiency endpoint is the expected turn cost of a hybrid policy: model-controlled play for at most L turns, followed by a declared brute-force resolver with the same clue character budget and two revealed-guess slots. Compare it with that reference policy from the initial state. The ideal endpoint is an expectation; the implemented finite Monte Carlo estimate is deterministic given its stored seeds and has separately reported numerical uncertainty.

The competitive endpoint is a batch Elo-style rating of paired cost comparisons: A+A attacking B and B+B attacking A on the same secret. Frequency of winning a cost comparison and magnitude of mean cost savings are different quantities; report both.

Optional role diagnostics measure receiver decoding, defender decoding and commitment-match prediction on objectively labeled tasks. These are distinct from overall game strategy and from game Elo. Hidden commitments are available to the referee as answer keys without becoming player-visible information.

A public finite dictionary permits eventual enumeration. The benchmark must show improvements beyond straightforward legal enumeration, including the researcher's first/last two-guess policy and any additional guesses permitted by the clue channel. It must also test simple blocklist policies, reveal/cancel behavior and encoding strategies.

Headroom among current models remains an empirical question. Development pilots must investigate saturation, cheap solutions, invalid-output effects, vocabulary effects and inference expenditure before confirmatory claims.

## 3 Rules supplied by the researcher and proposed benchmark choices

### 3.1 Clarified game rules

- The defender knows a secret word from a public dictionary. Guessers know a growing prefix.
- Guesser 1 and Guesser 2 are separate model instances with fixed roles.
- Guesser 1 announces a clue and privately registers its intended word.
- Guesser 2 privately registers one word. It can differ from Guesser 1's intended word.
- The defender sees the clue and may block any number of dictionary words, including zero. The blocklist is public.
- If both registered words are in the blocklist, neither guess is revealed. The defender is not explicitly told which blocked words were selected.
- If exactly one registered word is blocked, the unblocked guesser may cancel and keep its word hidden, or reveal it as a direct target guess. Interpret the researcher's phrase "one clue was blocked" here as one of the two registered guesses being blocked.
- Only publicly saying the target wins through a guess: private registrations, canceled guesses and silent thoughts do not test it.
- A matching unblocked pair earns the next actual prefix letter, unless a public target emission already ends the game. Earning the final letter wins immediately on that turn.
- Every publicly emitted dictionary word becomes ineligible for future contacts.
- A direct guess is also legal, as established earlier; a correct direct guess wins.
- Model play has a fixed turn cap.
- The first/last enumeration policy is a required baseline: Guesser 1 chooses the first remaining completion, Guesser 2 the last, and the policy always reveals when allowed. It guarantees a win within ceil(n/2) turns without useful clues or contacts.

Literal dictionary enumeration through the clue channel is legal within the character limit and must be implemented as another baseline. The researcher's illustrative budget is 100 characters; the exact production budget remains configurable.

### 3.2 Additional proposed defaults

These complete the implementation and remain reviewable design choices.

| Issue | Proposed default |
|---|---|
| Initial prefix | First character |
| Vocabularies | Same frozen list for secrets and contact words |
| Turn | One Guesser 1 direct action, or one complete clue round including any reveal/cancel decision |
| Timing | Staged round: sealed receiver/blocker decisions, public blocklist, conditional private choice, then resolution |
| Target-hit scope | Public gameplay emissions only; registration alone does not test the target |
| Receiver output | One word or pass |
| Blocklist | Arbitrary explicit finite subset of the dictionary; no extra cardinality cap |
| Neither word blocked | Open both guesses simultaneously; no optional cancellation |
| Exactly one word blocked | One private reveal/cancel decision by the unblocked seat, without replacing its committed word |
| Both words blocked | Open neither; no additional model call |
| Receiver pass | Open Guesser 1 if unblocked; otherwise open neither; no cancellation choice |
| Public disclosure | Clue, full admitted blocklist, only actually opened guesses, prefix/outcome and public state |
| Hidden feedback | Do not publish blocked-seat flags, hidden match/coverage, private pass status or cancellation choice/actor |
| Private history | Each seat retains only its own permitted commitments and decisions, plus public events |
| Used words | Publicly emitted dictionary words and any complete displayed prefix that is itself a dictionary word |
| Invalid reveal/cancel output | Cancel; record a model-invalid choice privately and charge the existing turn |
| Clue text | Printable ASCII, 1 to C characters after trimming; proposed initial C=100 |
| Literal-candidate count limit | None in the primary profile; a separate count-capped condition may be an ablation |
| Matched reference | Maximal feasible random-order batches using the C-character clue plus two distinct guesses; always reveal |
| Reference ordering | Fresh uniform word ordering on every reference turn; empty defender; no semantic contact |
| Reference expectation | Exact special cases and small-state oracle; otherwise full rollouts averaged within target-length classes |
| Main cap for development | L=20, with separate development sweeps |
| Probability reports during main games | Off; implement a separate frozen-clue audit first |
| Optional joint reporting | Separate versioned condition, private and exempt from gameplay emissions |
| Singleton candidates | No automatic win; an explicit winning action remains necessary |
| Word endings | Confirmed final-letter contact victory; no END symbol |
| Tools | No web, code execution, or private shared scratchpad during play |

The former k=4 count cap was an assistant proposal and is removed from the primary profile. The default C=100 is a proposed starting point, using the researcher's example; compare C=100 and C=240 on development data if useful, then freeze the production choice. Section 7 specifies a character-aware reference without requiring a count cap for convenient algebra.

The pass branch and private-feedback policy make unspecified edge cases executable. Freeze them explicitly before a main run. Do not grant a cancellation choice merely because a single registered word is blocked when the receiver passed; the exactly-one-blocked rule applies to two valid word commitments.

### 3.3 Confirmed public-utterance rule

A canceled, unrevealed registration of the actual target does not win and does not produce private evidence that the word is wrong. Registration is a commitment about what the player intends to say if the reveal rules permit it. Private records remain useful for enforcing consistency and scoring optional prediction tasks, but cannot trigger gameplay target hits or hidden target elimination.

Public target utterances and successful final-letter contacts are the two terminal routes. A complete displayed prefix that is a dictionary word also counts as an appeared/used word. If the game continues after displaying art, art is neither a possible target nor an eligible future contact. Completing the target prefix wins through the contact-completion rule. Do not restore the earlier mistaken private-hit, END or prefix-exemption interpretations.

## 4 Vocabulary, public emissions and admission

### 4.1 Lexicons

Maintain V_secret and V_contact as separate concepts, with identical files in the primary profile. A larger contact vocabulary is an optional condition. For the capacity-matched reference, require V_secret to be a subset of V_contact.

The production dictionary is a versioned researcher-selected input. Include a small explicitly licensed fixture list in the repository. Do not redistribute a source with unknown rights.

Record source/provenance, license, source revision/date, all preprocessing, exclusions, word count and SHA-256. Store sorted unique normalized words. The proposed production profile uses alphabetic English words of 3 to 20 characters; fixture lists may include shorter words. Legal membership is determined by the frozen list, not an LLM's opinion.

### 4.2 Word normalization and literal mentions

For registered words and block entries, strip surrounding ASCII whitespace, lowercase ASCII A-Z, and require one [a-z]+ word in the appropriate vocabulary. Reject internal whitespace, punctuation, multiple alternatives, stemming, spelling repair and synonym matching. Exine and exines differ.

For clue mentions, extract maximal ASCII alphabetic runs from the decoded clue string and lowercase them. Intersect these tokens with V_secret union V_contact to determine emitted dictionary words. Thus art is mentioned by "Art!" but not by artist; hyphens and apostrophes separate runs. State this behavior in the rules.

Parse JSON first. Escape sequences representing an actual word in a decoded gameplay field do not bypass scanning. Do not scan JSON field names or the serialized wrapper.

### 4.3 Public utterances and appeared words

Admitted public values in these gameplay channels count as target utterances:

1. Guesser 1's clue text.
2. Guesser 1's explicit direct guess, or its intended word if actually opened at the reveal phase.
3. Guesser 2's registered word if actually opened at the reveal phase.
4. Every explicit defender blocklist entry.

In addition, when the referee displays the current complete prefix, that exact prefix counts as an appeared word if it belongs to V_secret union V_contact. Add it to used_words at initialization and after every earned letter. This does not tokenize all substrings of a longer prefix: each actually reached complete prefix is processed once as its own canonical game event. Previously displayed word-prefixes remain used.

Private registration alone does not count. A blocked commitment need not be opened for its word to be used up: the defender has already said that word in the blocklist. Canceling prevents only opening the selected commitment. It cannot undo a clue mention, block entry, opened guess or displayed word-prefix.

Do not treat system prompts, supplied dictionary lists, schemas, summaries, private seat histories, private reasoning, rejected raw responses, hidden commitments or auxiliary probability reports as gameplay utterances. Otherwise dictionary access or an audit would itself win the game. Handle canonical prefix-display events explicitly rather than scanning arbitrary copies of a prefix in prompts: a contact reaching the full secret wins, and an ongoing dictionary-valued prefix is used up.

An output is not admitted merely because it appeared in a provider's raw response. There are two distinct operations: admitting a legal private commitment, and opening it as a public guess. Do not implement target detection by scanning every admitted gameplay subtree indiscriminately.

### 4.4 Admission and clue limits

Validate a gameplay submission using public rules before any of its public content is broadcast or considered for target hits.

For a clue action require:

- Valid action structure and a legal pre-turn intended word.
- Nonempty trimmed printable ASCII clue text of at most C characters, including spaces and punctuation.
- No separate count restriction on dictionary words in the primary character-only condition.
- No unexplained extra gameplay fields.

The intended word may appear in the clue and is then publicly emitted regardless of later cancellation. It can win by being the target, but it is already used for contact and cannot subsequently earn a letter that turn. Registration is admitted against the pre-turn word set; freshness for a contact additionally excludes current clue mentions. Repeated occurrences consume characters each time, although the appeared-word set deduplicates them. Whole words must appear within an individual clue: spelling fragments across turns does not concatenate into a target utterance. Use one ASCII space between words in enumeration baselines and count it against C.

Reject the entire invalid gameplay action without emitting its text. An overlong dictionary dump must not win first and incur a penalty afterward. Publish only a generic invalid_action marker for an invalid Guesser 1 action, not the attempted words or raw diagnostics.

For a clue-only enumeration baseline covering every target, validate maximum_secret_word_length <= C. A word longer than C cannot be fully spoken through that clue channel, although the combined reference can still use a registered-guess slot. The proposed 3-to-20-character lexicon and C=100 satisfy this requirement. A separately count-capped ablation must enforce its own literal-mention rule and use a matching scorer; never silently carry its fixed-b formula into the character-only condition.

A blocklist is an explicit array of vocabulary words. Empty is allowed. Normalize and deduplicate it; do not add, delete or correct choices based on the secret. A blocklist containing the secret is admissible and loses. No wildcard, complement or "all except" action is supported.

Provider output budgets remain declared resource constraints. For each primary lexicon/profile, preflight that a full explicit legal blocklist can be represented within the maximum permitted structured output; otherwise use a smaller lexicon, a sufficiently large output allowance, or a separately versioned dictionary-ID action encoding whose decoded words have identical game effects. Do not claim unrestricted explicit blocklists while silently truncating them.

### 4.5 Dictionary access and clue interpretation

All seats receive the complete pre-turn public secret-candidate and contact-eligible lists in stable alphabetical order. Host filtering is common assistance. No model must reconstruct the dictionary from memory while another gets a lookup tool. Lists must not omit a concealed commitment just because the referee has recorded it.

Preflight complete observations and permitted histories against context windows. Reject configurations that cannot fit; do not silently omit words or summarize selected models' histories.

Mechanical legality does not establish semantic naturalness. Public encodings, literal lists and ambiguous clues are legal if they pass the explicit rules. A semantic-clue condition requires a written rubric and a separate human audit or declared judging method. Keep its labels and results separate from mechanically scored games.

## 5 State and information boundaries

### 5.1 Public state and private records

The referee owns secret s, fixed vocabularies, private commitments and decisions, and these public state fields:

~~~text
prefix
turns_used
turn_limit
used_words
public_history
outcome_status
~~~

Keep operational collection_status separately. A proved public target hit can have outcome_status=solved while collection_status=incomplete because another response was unavailable. Unknown outcomes remain infrastructure_incomplete and have no score. Operational partial data must not be converted to a model pass or cancellation.

At a round boundary, derive:

~~~text
C_secret = {w in V_secret : w starts with prefix} minus used_words
C_contact = {w in V_contact : w starts with prefix} minus used_words
~~~

For identical vocabularies these sets coincide. The current prefix itself, if a dictionary word, is already in used_words and therefore absent from both sets. If a contact displays art and play continues, art cannot be the target and cannot earn another contact: it has appeared. All remaining candidates in an ongoing game must be strictly longer than the prefix. Initialization requires a prefix strictly shorter than the sampled secret and marks any dictionary-valued initial prefix as used.

Every counted appeared secret-vocabulary word is known not to be s if play continues. There is no surviving-game category of an appeared word that is retired but still a possible target. Prefix filtering can independently rule out words that have not appeared and simply no longer match the longer prefix.

A canceled unblocked word stays out of used_words only if it has not otherwise appeared through a clue, block, opened guess or complete displayed prefix. It remains eligible only if it also fits the current prefix and relevant vocabulary. Mere registration cannot add a negative target label. Its owner remembers the commitment; the referee cannot silently share it with the teammate or defender.

Before any valid nonterminal continuation, s must remain in C_secret and its size must be at least one. Snapshot both candidate sets at turn start for registration admission. For a contact award, also exclude words already mentioned in the current clue or blocklist. The simultaneous guess openings are the contact declaration itself and do not disqualify their own otherwise-fresh match. Commit the completed public state after resolution; do not confuse this implementation order with permission to reuse a word already said in the clue.

Private audit state includes w1, w2/pass, blocked membership, reveal eligibility, reveal/cancel choice, opened flags, raw/canonical action validity and optional forecasts. Maintain separate per-seat permitted histories. Audit state is never automatically serialized into observations or public state.

### 5.2 Observation matrix

| Information | Guesser 1 | Guesser 2 | Defender | Referee |
|---|---|---|---|---|
| Rules, cap, public state and candidate lists | Yes | Yes | Yes | Yes |
| Labeled secret identity | No | No | Yes | Yes |
| Public clue | Yes | Yes | Yes | Yes |
| Guesser 1's unexposed commitment | Own word | No | No | Yes |
| Guesser 2's unexposed commitment/pass | No | Own action | No | Yes |
| Defender's blocklist before it is published | No | No | Own output | Yes |
| Full admitted blocklist once published | Yes | Yes | Yes | Yes |
| Actually opened guesses | Yes | Yes | Yes | Yes |
| Hidden blocked/canceled commitments afterward | Own only | Own only | No | Yes |
| Cancellation eligibility and private choice | Only if acting seat | Only if acting seat | No | Yes |
| Hidden match, coverage and blocked-seat flags | No extra disclosure | No extra disclosure | No extra disclosure | Yes |
| Auxiliary reports during play | Own report only | Own report only | Own report only | Yes |
| Target-generation seed and private task manifest | No | No | No | Yes |

The eligible cancellation prompt necessarily tells the acting seat that its partner's committed word was blocked. It must not reveal which word. Other seats receive no explicit cancellation prompt, eligibility flag or choice record. Natural inference from public clues, blocklists and opened guesses is permitted; the engine must not add hidden labels to make that inference easier.

For example, publicly reporting "both blocked" with a one-word blocklist would identify both commitments by deduction. Therefore public history records the full blocklist, any actually opened guesses and a neutral no-prefix result, without distinguishing both-blocked from canceled or otherwise unsuccessful hidden branches. Hidden pass and per-responder validity flags also remain outside public history; the owner sees its own canonical action status.

Roles stay fixed within a game. Give each seat a fresh isolated context per game, including both role-swapped legs. Never transfer a defender's history to an attacker. No opponent model names, private teammate negotiation, correlated secret coordination seed, cross-game memory or external tools are supplied in the main track.

Construct observations from explicit allowed fields, not a complete referee state with redaction. Keep phase scheduling, request identifiers, timing, audit counters and postgame diagnostics out of live player observations. Each seat may remember its own prior admitted commitments and private choices; a shared team memory is not supplied.

### 5.3 Staged sealed round

After a valid clue action, collect Guesser 2's word/pass and the defender's blocklist independently from the same pre-resolution public state and clue. Neither sees the other's response, stream, timing or validation feedback. The defender does not receive w1, w2 or a marked intended-word identity.

The proposed collection policy issues both initial responder decisions even when a public clue mention already proves a target hit. This preserves the complete initial response cohort; record the extra resource cost. This is a collection choice, not permission to treat the private commitment as a hit. A separately specified early public-hit stop can save calls but changes which diagnostic responses exist.

Persist commitments and both initial responses. Publish the full admitted blocklist. A public hit in clue or blocklist ends the round before any optional reveal decision. Otherwise select the reveal branch from the commitments' membership in the blocklist. At most one additional decision is needed, by the sole unblocked seat when both valid word commitments exist and exactly one is blocked.

That private prompt contains public state, clue, blocklist, the actor's own committed word and the fact that the partner's word was blocked. It contains no partner identity or hidden-match diagnostic. Its strict output is reveal or cancel; it cannot revise the word, issue another clue or add a new guess.

Both initial responses and any conditional choice remain part of the same game turn. Finish every required phase before applying the turn cap. Do not grant a fresh turn for cancellation or a new attempt after it.

## 6 Actions and resolution

### 6.1 Gameplay schemas

Use strict JSON objects with no extra gameplay fields. Provider schema enforcement does not replace local membership and semantic validation.

Guesser 1:

~~~json
{"action": "clue", "word": "candle", "clue": "Wax surrounding a wick"}
~~~

or:

~~~json
{"action": "direct", "word": "candle", "clue": null}
~~~

A clue's intended word must belong to pre-turn C_contact. A direct word must belong to pre-turn C_secret. The clue field is public; the intended-word field is initially private.

Guesser 2:

~~~json
{"action": "guess", "word": "candy"}
~~~

or:

~~~json
{"action": "pass", "word": null}
~~~

A word belongs to pre-turn C_contact. It may be a strategic secret guess rather than the most probable intended word. Do not force it to match a separately elicited forecast's argmax. This permits the researcher's first/last baseline. The word remains private until the reveal rules open it.

Defender:

~~~json
{"action": "block", "words": ["camera", "carrot"]}
~~~

An empty words array means no blocks. Entries must belong to V_contact; previously used or irrelevant-prefix entries are redundant but not secret-dependent validation errors. Blocklist words need not be a forecast's support or exceed a probability threshold.

Conditional action by whichever guesser is unblocked:

~~~json
{"action": "reveal"}
~~~

or:

~~~json
{"action": "cancel"}
~~~

This action has no word or free-text field. Reveal opens the existing sealed word; cancel leaves it unspoken. Reject attempts to substitute a new word. The optional diagnostic envelope in Section 8 is separately validated and never public gameplay text.

### 6.2 Direct action

A valid Guesser 1 direct action consumes one turn and publicly emits its word. It wins if its word is s; otherwise add it to used_words. No receiver or defender call occurs.

Guesser 1 keeps its role on the next turn. A used secret word cannot be a legal future direct guess because survival already established that it was wrong.

### 6.3 Clue-round resolution

Let w1 be Guesser 1's intended word, w2 Guesser 2's admitted word or pass, H the admitted public block set, and M the dictionary words literally mentioned in the admitted clue. Let O be the role-labeled set of guesses actually opened by the following rules; deduplicate only when computing word sets, not role attribution.

First check s in (M union H). If true, offense wins on the current turn. Do not open hidden commitments merely to populate a terminal transcript. Otherwise use this table:

| Registered words and blocking | Opened guesses O | Extra decision | Prefix contact possible? |
|---|---|---|---|
| Two words, neither blocked | Open both simultaneously | None | Yes, if equal and not already named in the clue |
| Two words, both blocked | Open neither | None | No |
| Two words, exactly one blocked; survivor reveals | Open only the unblocked word | One | No |
| Two words, exactly one blocked; survivor cancels | Open neither | One | No |
| Receiver passes; Guesser 1 unblocked | Open Guesser 1 | None | No |
| Receiver passes; Guesser 1 blocked | Open neither | None | No |

Exactly one blocked implies w1 != w2: equal words would have identical membership in H. The conditional choice therefore cannot earn a prefix symbol on the current turn. It chooses between a direct target test and preserving a potentially useful future contact word.

After the table:

~~~text
emissions = M union H union words(O)
target_hit = (s in emissions)
registered_match = (w2 is a word and w1 == w2)       # referee diagnostic
intended_covered = (w1 in H)                         # referee diagnostic
fresh_for_contact = (w1 not in pre_turn_used_words and w1 not in M)
contact = both_guesses_opened and registered_match and fresh_for_contact
~~~

Use pre-turn eligibility for registration validation, then the additional current-clue freshness check for contact. Both opened guesses are necessarily absent from H under the reveal table.

1. Any target_hit wins now, regardless of whether the guessers matched.
2. Otherwise, if contact, reveal exactly one next actual letter. If the resulting prefix equals the secret, offense wins immediately with terminal_reason=prefix_completed.
3. Otherwise, reveal no prefix letter.
4. Publish only the clue, full blocklist, actually opened role-labeled guesses, resulting prefix/outcome and public state. A no-prefix public event does not carry a hidden reason code.
5. Add all public utterances and any new complete displayed prefix that is a dictionary word to used_words. Do not add unopened commitments merely because they were registered.
6. If not terminal, recompute the public candidate sets and apply the cap.

Track actual public hit sources: clue, opened Guesser 1 word, opened Guesser 2 word, blocklist or direct guess, with terminal_reason=public_target_utterance. Multiple public sources can occur. A private commitment equal to s is not a hit source. Prefix completion is a separate terminal reason and is not attributed to a spoken target channel. Audit fields for registration truth, match and coverage remain private during play.

Record `registered_match`, `intended_covered`, each seat's blocked membership and `covered_match = registered_match and intended_covered` in the referee audit. Define an actually prevented ordinary contact as `blocked_contact = not target_hit and covered_match and fresh_for_contact`. A public target hit has already ended the game, and a word spelled in the clue was already disqualified from earning a letter; neither is counted as a prevented prefix award. A covered intended word with a different receiver word also did not prevent a match. These diagnostic flags are not public feedback when identities remain hidden.

### 6.4 Final-letter contact victory

The secret's length is not explicitly given to the guessers. Initialize a scored game only with len(initial_prefix) < len(secret). A successful unblocked contact appends exactly the next actual letter. If the resulting prefix equals the complete secret, declare victory immediately on this turn. There is no END symbol, additional contact or spoken confirmation required.

Example: with secret art and prefix ar, a successful contact on the nonsecret word arch reveals t and wins. With secret artist, the same contact reveals t but the game continues. The displayed prefix art has now appeared as a dictionary word: exclude it both as a target and as a future contact. It does not remain eligible merely because no guesser separately spoke it. Reflect this in supplied lists and fallback state.

Process this canonical prefix event explicitly. The first example wins through the contact-completion rule; record terminal_reason=prefix_completed separately from public_target_utterance. Both examples mark dictionary-valued displayed prefixes as appeared words, while ordinary copies in input dictionaries, prompt summaries and schemas do not create new utterances.

A singleton target set does not automatically win merely because the answer is inferable: an explicit public guess or a successful completing contact is still required, and the fallback charges its final turn. A fully earned secret prefix is already terminal and must never be represented as an ongoing singleton state.

### 6.5 Invalid outputs, incomplete collection and cap

An invalid Guesser 1 gameplay action consumes one turn, emits no words and triggers no responders. Publish only turn/seat plus invalid_action. Invalid Guesser 2 gameplay becomes a private canonical pass; invalid defender gameplay becomes an empty public blocklist. Invalid reveal/cancel output becomes cancel. Preserve model-invalid labels in audit and the acting seat's own history, without echoing rejected raw text or hidden actions into public history.

Admission precedes public target detection. Validity must not depend on whether a valid clue, blocklist or commitment contains s. A valid public target emission wins; a private commitment containing s is legal but remains untested until opened in this profile.

Refusal, malformed model output and selected output-budget exhaustion are model behavior under the declared penalties. Transport failures, authentication problems, quotas and unavailable providers follow Section 14. Retries do not create free new decisions. An unavailable cancellation response is not an automatic cancel.

Fully resolve turn L, including a required reveal/cancel decision; a public target hit or final-letter contact then wins at cost L. If unsolved, stop model play and compute the reference completion expectation from public C_secret using Section 7's numerical procedure. No model turn L+1 occurs. A pending or infrastructure-incomplete round is not an ordinary capped game.

A known admitted public winning emission gives outcome_status=solved and effective_cost=t even if another response is unavailable; set collection_status=incomplete. Preserve winning evidence and attempt configured recovery. Unobserved match, coverage, openings and additional public hit-source fields remain unknown, not false or pass. Mark observed hit-source completeness explicitly. Both known game costs suffice for a paired cost result despite incomplete auxiliary collection.

**A private committed word equal to s does not prove a win.** Missing blocking or reveal decisions may determine whether it is ever said. Sufficient admitted decisions proving a successful final-letter contact can also establish a known win. If neither a public target emission nor a completed contact establishes the outcome, leave the game infrastructure_incomplete and unscored until recovered.

### 6.6 Worked mechanics fixture

Use the ten-word fixture cable, camera, candle, candy, canoe, carrot, castle, cobra, comet and crane. Secret: candle. Initial prefix: c. Cap: four. This table is an omniscient audit illustration, not the live defender view or evidence of good model play.

| Turn | Guesser 1 private word and public clue | Guesser 2 private word | Public blocklist | Revelation and result |
|---|---|---|---|---|
| 1 | carrot; "An orange root vegetable" | castle | camera, carrot | Guesser 2 cancels. Neither commitment opens. Only camera and carrot are used; castle is preserved; 8 candidates remain. |
| 2 | castle; "A fortified home with towers" | castle | comet | Neither blocked, so both open. Contact reveals ca. Used words now include castle and comet; candidates are cable, candle, candy, canoe. |
| 3 | candle; "Wax surrounding a wick" | candy | Empty | Both open. Offense wins because Guesser 1 reveals the secret despite the mismatch. |

The public first-turn transcript contains the clue, H={camera,carrot}, no opened guesses and a no-prefix outcome. It does not identify the committed carrot or castle, the blocked seat or the cancellation actor. The referee audit and each seat's own permitted history retain the appropriate details.

With proposed C=100, all ten fixture words fit in one combined enumeration turn: reserve two as guesses and put the other eight in the clue. Its reference cost is therefore exactly 1 and its realized model cost is 3. It illustrates mechanics, not an efficiency gain. A production difficulty profile should not consist entirely of such one-turn enumeration tasks.

Separate regression: w1=candle, w2=carrot, H={carrot}, clue="Wax surrounding a wick", and Guesser 1 cancels. This does not win: candle was not publicly said and remains a candidate at prefix c. Revealing instead wins. Another case with both guesses in H must keep both identities hidden while retiring all of H. Include the art/artist final-letter examples as separate boundary fixtures.

## 7 Character-budget enumeration and completion scoring

### 7.1 Required first/last baseline

Guesser 1 registers the alphabetically first current target candidate, Guesser 2 the last, with a neutral clue such as "?". Always reveal when offered cancellation. Each chosen word is then publicly emitted either by the blocklist or by its guesser. Every surviving turn removes at least two candidates when two remain. Blocking the target itself loses; the final singleton is guessed directly.

For n candidates this guarantees a win within ceil(n/2) turns against any defender. With an empty blocklist, no additional clue emissions and a uniform target, its uncapped mean is:

~~~text
F_2(n) = (n+2)/4             when n is even
F_2(n) = (n+1)^2/(4*n)       when n is odd
~~~

For n=100, worst case 50 and mean 25.5. Other defenders can accelerate it with extra public negatives. These means also hold with a cap followed by the same two-guess reference; they do not describe its hybrid cost when the stronger character-packing fallback below takes over. Keep first/last as a required diagnostic baseline, not the primary capacity-matched reference.

### 7.2 Clue-only dictionary listing

Implement a nonsemantic baseline that lists remaining target candidates in alphabetical order, placing as many consecutive whole words as fit in each clue, separated by one ASCII space. Never split a word across clues. Choose Guesser 1's registered word from that clue and make Guesser 2 pass, so registration creates no additional candidate test and no prefix award. Extra blocklist words may help but are not needed. Include reverse-order and shuffled-order comparisons.

For a fixed order, the worst-case number of turns against an empty defender is the number of legal clue chunks needed to exhaust the initial candidate set. Compute that number by the actual packing procedure. It is not generally ceil(total_characters/C): indivisible words and separators cause unused space. For example, "cat dog pig" has 11 characters including spaces, but C=6 allows only one word per clue, so three clues are necessary rather than ceil(11/6)=2.

Let D=sum(word lengths)+(n-1) be the size of a space-separated dictionary. D/C is a throughput approximation, not a universal upper bound for this clue-only policy. If a word exceeds C, this particular policy cannot cover it at all; validate the lexicon/budget combination. The combined policy below has a stronger guarantee because it uses the two additional word slots.

### 7.3 Combined clue-plus-two-guess packing

The primary reference uses both legal channels: a literal word list in the clue and up to two additional revealed guesses. It has no semantic communication, prefix-seeking strategy or model calls.

For a proposed batch G, assign its two longest words to the two guess slots and put the rest in the clue separated by one space. Any deterministic tie-break among equal lengths gives the same tested set and clue length. Define a(w)=len(w)+1 and Q=C+1. For |G|>=3, feasibility is exactly:

~~~text
sum(a(w) for w in G) - largest_weight(G) - second_largest_weight(G) <= Q
~~~

The remaining weights include one space after each clue word; subtracting the final space gives the actual clue length. With two words use clue "?" and distinct registered guesses. With a singleton use a direct guess. Every such batch consumes one game turn. The two registered guesses are distinct whenever there are two, so the reference cannot obtain ordinary contact letters.

Given a candidate ordering, accept its longest initial segment satisfying this feasibility test. Stop at the first word that would make the segment infeasible; do not skip that word to pack later words. The rejected extension remains untested. The next reference turn starts afresh as specified below. This is an explicit greedy policy, not a claim of globally optimal bin packing.

Both guessers always reveal when offered cancellation. A selected word is therefore tested through either the clue, the public blocklist or an opened guess. Use an empty defender for reference scoring; separately run baselines against model and scripted defenders to measure their information disclosures.

#### A useful worst-case bound

Let n be the initial candidate count and A=sum(len(w)+1)=D+1. Every nonfinal maximal combined batch has total weight greater than Q. To see why, let its total weight be a, its two largest weights u>=v, and the rejected next weight x. If x<=v, failure means a+x-u-v>Q, hence a>Q+u. If x>v, failure means a-u>Q, again a>Q+u. The final batch is nonempty.

Consequently, even if the remaining words are freshly reordered between turns:

~~~text
worst_case_turns <= min(ceil(n/2), ceil(A/(C+1)))
                 = min(ceil(n/2), ceil((D+1)/(C+1)))
                 <= ceil(D/C)
~~~

This last bound uses a dictionary length D that includes one separator between words. With D=1,000,000 and C=100, the combined bound is at most 9,901 turns, hence certainly within the researcher's 10,000-turn illustration. The two guess slots compensate for the boundary waste that invalidates the same general claim for clue-only output. If the quoted dictionary size counts letters alone, add separator overhead before applying the formula.

These are worst-case bounds, not expected completion times or the primary score. Always enumerate only public remaining target candidates; searching the entire unfiltered lexicon is an unnecessarily weak reference after prefix progress.

### 7.4 Primary reference policy: fresh random ordering each turn

Define the policy completely:

1. Start from the public remaining target set S.
2. Draw a fresh uniform random ordering of S, independently on each reference turn.
3. Take its maximal feasible initial segment under Section 7.3.
4. Execute that batch with an empty defender and always-reveal behavior.
5. If the target was not tested, remove the batch and repeat from the remaining set.

The policy has no knowledge of which candidate is the secret. It uses no hidden commitments, private forecasts or hidden negative labels. It never filters candidates by the actual secret length. It can be implemented as sequential uniform draws without replacement until the first infeasible extension, rather than materializing and sorting the entire permutation on every turn; put the failed extension back into the untested pool for the next fresh draw.

Fresh ordering on every turn is deliberate. A single preselected order with greedy word boundaries, followed by a new random order at the cap, is a different hybrid. The memoryless definition here gives the same continuation distribution whenever the current candidate set is the same.

Let R_C(S,s) be this policy's ideal expected number of further turns to publicly guess fixed target s. Because the policy treats word identities uniformly and uses only lengths for packing, R depends only on the length histogram h of S and target length ell=len(s):

~~~text
R_C(S,s) = R_C(h,ell)
~~~

All candidates of the same length have the same reference expectation. There is no alphabetical-position preference. Different target lengths may have different costs because they fit into legal batches differently; that is a property of the declared reference.

The scorer uses the known answer to evaluate when a secret-independent policy would reach it. Looking up R(h,len(s)) does not give the policy the secret's length or authorize secret-dependent candidate pruning. Policies and player prompts still use only permitted public state.

### 7.5 Exact cases and small-state oracle

Return R=1 exactly whenever the entire candidate set fits in one combined batch, including a singleton.

If all n words have the same length ell, every full batch has capacity:

~~~text
b = 2 + floor((C+1)/(ell+1))
R_C(h,ell) = F_b(n) = (1/n) * sum(r=1..n, ceil(r/b))
~~~

Writing n=b*q+m, 0<=m<b:

~~~text
F_b(n) = [b*q*(q+1)/2 + m*(q+1)] / n
~~~

This recovers the former count-based formula as a special case rather than imposing an extra word-count cap on the game. For C=100 and ell=20, b=6 and F_6(100)=221/25=8.84. With ell=5, b=18 and F_18(100)=33/10=3.3. Character capacity changes the appropriate baseline substantially.

An optional additional exact shortcut applies when floor((C+1)/(ell_min+1)) and floor((C+1)/(ell_max+1)) are equal: every ordering then has the same full-batch cardinality, even if lengths differ.

For small mixed-length states, implement an independent exact rational oracle. Let P_h(v) be the probability that one reference turn selects length-count vector v. Obtain it by enumerating sequential uniform draws, stopping at the first infeasible extension and retaining that extension in the remaining set. Then:

~~~text
R(h,ell) = 1 + sum over v with v[ell] < h[ell] of
    P_h(v) * (1 - v[ell]/h[ell]) * R(h-v,ell)
~~~

Use exact rational transition probabilities and memoization. Each recursive step removes a nonempty batch. This oracle is for tiny fixtures or states within an explicit computational limit; do not promise tractable exact enumeration for every production histogram.

### 7.6 Reproducible estimation for general mixed lengths

For larger mixed-length states, simulate K independent complete reference enumerations, continuing hypothetically until every candidate has a turn rank. The reference actions are independent of the target, so one complete trajectory can score every possible target length. It is sufficient to simulate a multiset of lengths; there is no need to send words to an LLM.

In rollout r, let T[r,i] be the turn in which candidate i is tested. For each length ell with h[ell]>0, compute:

~~~text
Z[r,ell] = sum(T[r,i] for i with length ell) / h[ell]
R_hat(h,ell) = sum(Z[r,ell] for r=1..K) / K
~~~

This averages over the exchangeable identities in the target's length class. It is an unbiased estimator of the ideal expectation, reduces sampling variance, and makes finite estimates exactly invariant to alphabetical relabeling within a length class. Do not score only one arbitrarily named target's rank when the other same-length ranks are available.

Store the accumulated integer rank total and denominator K*h[ell] as an exact reduced fraction. That fraction is the exact mean of the simulated sample; it is not generally the exact infinite-randomization expectation. Keep that distinction in exports and prose.

Report numerical standard error:

~~~text
MCSE(R_hat) = sqrt(sum_r (Z[r,ell]-R_hat)^2 / (K*(K-1)))
~~~

The independent units are complete rollouts, not words within a rollout. Store sufficient rollout-level statistics to audit standard errors and paired differences. With equal lengths, every rollout's class mean already equals F_b(n), so the variance is zero.

Proposed starting configurations are K=2,048 for development and K=4,096 for a final run, subject to development precision checks. These numbers do not guarantee a particular error bound. Freeze the estimator, seeds, exact-state threshold, sample count and any predeclared refinement rule before examining final model rankings. Increase numerical effort where uncertainty can change substantive comparisons, using the frozen rule and shared cache rather than selectively favorable reruns. Do not silently clip or round inconvenient estimates.

Cache the whole vector R_hat(h,ell) by canonical length histogram, C, packing/RNG versions, seed-ensemble identity and K. Reuse identical states across targets and models. Seed generation must not depend on the target identity, target length label, model identity or observed model score. Derive reproducible rollout seeds from a referee-held root seed and public-state histogram plus rollout index; the root is independent of target generation. Publish the seeds, RNG specification and cache provenance with released scores. Withhold scoring seeds from live players so numerical sampling artifacts are not an extra optimization target.

This scorer is objective and reproducible but numerically estimates an expectation. Distinguish its Monte Carlo uncertainty from uncertainty due to sampled game targets and model behavior. A fixed seed makes estimates reproducible; it does not remove their approximation error.

### 7.7 Model game cost and normalization

Let S0 be the initial public target set, SL the final public target set of an unresolved game, L the turn cap, and t a winning turn. The ideal quantities are:

~~~text
B = R_C(S0,s)
C_game = t                         if won by utterance or final-letter contact
C_game = L + R_C(SL,s)             if unresolved after fully resolving turn L
~~~

Use exact R where available and R_hat otherwise. Preserve rational numerators/denominators for stored point estimates and exact comparisons of those point estimates. Record numerical uncertainty alongside them. Do not rebaseline after progress or substitute the unfiltered dictionary for SL. A singleton costs one fallback turn. No model calls execute the fallback.

If the same memoryless reference policy controls the first L turns against an empty defender, then with ideal R:

~~~text
E[C_game | S0,s] = R_C(S0,s) = B
~~~

This follows from the continuation recursion and holds for each fixed target. It does not imply exact unit speedup in a finite run or with noisy R_hat values. Alphabetical listing, first/last and one-fixed-permutation policies are different policies; measure their costs rather than asserting the same identity for them. A score above one is not by itself evidence of semantic contact skill.

For the ideal reference, deleting nontarget candidates cannot increase R. Couple a fresh uniform permutation of the larger set with its restriction to the smaller set. Feasible groups remain feasible under deletion, so the smaller process tests every surviving member of the larger process's batch, possibly more. Repeating this coupling preserves inclusion of the remaining sets and cannot delay a fixed target. Thus a final-turn reveal weakly dominates cancellation for the ideal objective. Finite Monte Carlo estimates can violate this through numerical noise; do not present exact sample monotonicity as a theorem or silently repair estimates to force it.

Aggregate:

~~~text
aggregate_speedup = sum(B) / sum(C_game)
fraction_of_turns_saved = 1 - sum(C_game) / sum(B)
mean_effective_cost = sum(C_game) / number_of_games
mean_turns_saved = sum(B - C_game) / number_of_games
~~~

Do not average per-game ratios. Larger reference search costs contribute more to the aggregate; report difficulty strata and candidate-length distributions. A nonuniform target prior permits better informed orders; declare the prior and include corresponding guessing baselines.

Retain model mistakes. Infrastructure-incomplete unknown outcomes have no score and cannot become capped losses. A completed game may have a separate pending numerical-scoring status while its known gameplay outcome is preserved.

### 7.8 Why forward/reverse packing is not the primary scorer

Reversing word order and repacking does not generally cancel target ranks. With ant, bee and carrot, C=10, clue-only forward chunks are [ant bee], [carrot]; reverse chunks are [carrot bee], [ant]. The three target averages are 1.5, 1 and 1.5.

Reversing the order of the same fixed chunks without repacking would yield exactly (number_of_chunks+1)/2 for every target. That is a valid different reference, but randomizing unequal fixed groups can be substantially weaker than randomizing words and filling the budget. With a legal constant capacity of 100 and 101 targets, fixed groups of 100 and 1 in random order cost 1.5 on average, while random-word enumeration costs 102/101. Do not introduce an apparent model gain merely by substituting the weaker fixed-group reference without saying so.

The primary policy therefore randomizes words afresh and accounts for their lengths. The former fixed-b forward/reverse counterexample for n=5,b=2, with target averages [2,1.5,2,1.5,2], remains a useful legacy fixture; its uniform-word reference is F_2(5)=1.8.

### 7.9 Required numerical fixtures

| Quantity or condition | Expected result |
|---|---|
| First/last, n=100, no extra eliminations | Worst case 50; uniform-target uncapped mean 51/2 |
| First/last, n=5 | Uniform-target uncapped mean 9/5 |
| Clue-only cat/dog/pig, C=6 | Three clues despite 11 total serialized characters |
| Any candidate set fitting one combined batch | Reference cost exactly 1 |
| Equal lengths 20, C=100, n=100 | b=6; R=221/25 |
| Equal lengths 5, C=100, n=100 | b=18; R=33/10 |
| Length histogram {3:2,8:3}, C=8 | R(target length 3)=5/4; R(target length 8)=13/10; uniform-target mean 32/25 |
| Unsolved singleton at cap L | Cost L+1 |
| Final-letter contact at turn L | Cost L, terminal_reason=prefix_completed |
| Dictionary D=1,000,000 including separators, C=100 | Combined worst-case bound <=9,901 |
| Same candidate-length histogram and target length | Identical cached reference estimate irrespective of spelling |

For a ratio-of-totals regression, use C=1 and four equal three-letter fixture words, so only the two guess slots are useful. With cap L=1 and a fixed first pair, costs are [1,1,2,2], B=1.5, aggregate speedup 1, and the incorrect mean of per-game ratios is 1.125. This is a combined-reference fixture; clue-only enumeration is not supported at that deliberately tiny character budget.

## 8 Probability forecasts and role evaluation

### 8.1 Separate observations from actions

Probability reports are optional private diagnostics. They never trigger secret hits, word retirement, public disclosure during play or feedback into later player observations.

This exception is necessary: a distribution whose support includes the secret must not itself count as saying the secret. Only the gameplay channels in Section 4 count.

Ask each forecaster about Guesser 1's already committed intended word W:

~~~text
q_receiver(w) = P(W=w | receiver observation)
q_defender(w) = P(W=w | defender observation)
~~~

The support is the pre-turn C_contact. The answer key is W, not the hidden target s. The defender has different information because it knows s.

At the sealed initial-response boundary, W may equal s even in a round that later continues: the guess can remain hidden through cancellation. The defender may legitimately assign probability to W=s even though selecting s as an actual block loses. Prediction and action are distinct. Do not force the receiver's chosen word to be the argmax forecast or the blocklist to be a probability threshold set.

The referee's private precommitted W is the objective answer key whether it is opened, blocked or canceled. Scores and answer keys remain outside live player observations. Do not restrict prediction scoring to publicly revealed guesses: revelation is selected by blocking and cancellation policies and would change the evaluation population.

These are elicited probability reports, not direct measurements of internal token probabilities. Assess their calibration empirically.

### 8.2 Proper prediction scores

Use the following higher-is-better affine Brier score as the primary diagnostic:

~~~text
S_B(q,W) = 1 - sum_v (q(v) - indicator[v=W])^2
         = 2*q(W) - sum_v q(v)^2
~~~

Its range is [-1,1]; perfect prediction scores 1, certainty on a wrong word scores -1, and a uniform forecast on M words scores 1/M.

For a true conditional distribution p:

~~~text
E_p[S_B(q,W)] = ||p||^2 - ||p-q||^2
~~~

Thus reporting p uniquely maximizes the expected score when p is representable. With a constrained sparse reporting family, the score remains a proper scoring rule on full distributions, but the model can only report the best available approximation in that family. Do not claim the sparse format recovers arbitrary beliefs.

Do not use mean q(W) as the main probability score: a belief (0.6,0.4) earns expected 0.52 when reported honestly under that linear rule, but 0.6 when falsely reported as (1,0).

Optional log score is log q(W). A realized zero probability means negative infinity. Record zero-probability failures explicitly; do not silently clip and label it the unmodified log score. Any smoothing defines a declared transformed forecast.

Gneiting and Raftery (2007), cited in Section 21, provide the proper-scoring framework. The conditional tasks and applications here are benchmark design choices.

### 8.3 Sparse forecast format

Support up to 20 explicit entries plus residual mass. For example:

~~~json
{
  "entries": [
    {"word": "candle", "probability": 0.6},
    {"word": "candy", "probability": 0.2}
  ],
  "other_mass": 0.2
}
~~~

Let M be support size, h the number of distinct listed words, and a the residual mass. Define the full forecast:

~~~text
q(w) = listed probability             if explicitly listed
q(w) = a / (M-h)                      otherwise
~~~

If h=M, require a=0. Validate unique support entries, finite probabilities in [0,1], and total mass one. Permit only a predeclared small floating tolerance, proposed 1e-6, followed by deterministic renormalization; do not invent missing probabilities or repair substantial errors.

For M>h:

~~~text
sum_v q(v)^2 = sum_listed probability^2 + a^2/(M-h)
~~~

When the true word is omitted, its probability is a/(M-h), not the entire OTHER mass. Scoring a model-chosen OTHER bucket as if it were one word would reward hiding many possibilities in that bucket.

Store the schema, support, raw report, interpreted distribution and validity status. Forecast identifiers are private diagnostics even if they spell s.

In joint-live mode use an explicit wrapper, for example for Guesser 2:

~~~json
{
  "gameplay": {"action": "guess", "word": "candy"},
  "diagnostics": {
    "intended_word_forecast": {
      "entries": [
        {"word": "candle", "probability": 0.6},
        {"word": "candy", "probability": 0.2}
      ],
      "other_mass": 0.2
    },
    "commitment_match_forecast": null
  }
}
~~~

The defender uses its blocklist gameplay schema in the same wrapper. Only Guesser 2 and the defender report intended-word forecasts; Guesser 1 already knows its own commitment. Parse the whole JSON, then validate gameplay and diagnostics independently. Compute wins and used words only from the public emissions selected by the game state machine, not from every field of an admitted gameplay object. A hidden commitment or diagnostic field cannot create an extra guess or block.

### 8.4 Collection modes

Implement three explicit modes:

- off: main game prompts request only actions.
- shadow_audit: after freezing an item bank, make separate isolated forecast calls from saved pre-resolution observations without disclosing outcomes.
- joint_live: request actions and forecasts together; keep reports sealed and separate from public gameplay. This changes prompts and resource use and defines a separate condition.

Start research with off for main games and a small shadow_audit. The software should support the schema and scoring without making every tournament call emit a full forecast.

Do not infer an unseen shadow player's counterfactual hard action from a forecast unless a fixed policy rule is part of that audit. Do not score a forecaster on its own sampled future action as though that were an exogenous label.

Use separately validated action and diagnostic fields in joint mode. An otherwise parseable legal gameplay action is not invalidated merely because an auxiliary probability total is wrong. An unparseable whole response remains an output failure. Report missing/invalid forecasts and never silently omit them to improve means. For a scheduled forecast request, in either standalone or joint-live conditions, assign model-invalid reports score -1 in the overall Brier diagnostic, also reporting valid-report means and coverage. Structural absence or an infrastructure-unavailable response is not a model-invalid forecast; apply the declared completion/missing-data policy and report it separately.

### 8.5 Defender decoding versus commitment-match prediction

The defender's decoding score measures how well it identifies W. Blocking strategy also depends on whether Guesser 2 will match.

An optional commitment-match forecast has categories each pre-turn contact word plus NO_MATCH:

~~~text
P(W=w and receiver_answer=w | defender observation)
P(NO_MATCH | defender observation)
~~~

The observed label is W if the two registered words agree, otherwise NO_MATCH. The referee can score this label from private commitments even when both remain blocked and unopened, or when a separate public target hit ends the game. Call it a commitment-match forecast: it does not directly predict an awarded prefix letter or public revelation. Report ordinary nonsecret opportunities separately if making claims about preventable prefix awards. An actual-contact forecast would need a distinct target definition incorporating the selected blocklist and resolution rules.

For shadow audits, label this as predicting the recorded receiver policy's answer. For joint-live forecasts, collect before the defender sees that receiver answer. Include observed model-invalid receiver outputs as NO_MATCH in the primary commitment-match prediction target, consistent with their canonical pass game effect. Report a valid-receiver-only subset as a conditional descriptive diagnostic, not as the same unconditional proper-score target. An infrastructure-unobserved receiver answer is unknown and cannot be labeled NO_MATCH. This prevents post-hoc validity filtering from penalizing an accurate prediction of receiver failure.

Do not combine decoding or commitment-match forecast scores into game Elo. Actual blocklist strategy is still evaluated by offensive completion cost.

### 8.6 Comparable role and clue-giving evaluations

Raw averages from different live trajectories are not controlled role comparisons: earlier play determines which clues and states each model encounters.

Create a frozen clue bank containing public state, clue, committed intended word, secret, provenance and validity labels. Include blocked, canceled and opened commitments using a predeclared sample; do not select only public successes or reveals. Give every candidate receiver the same receiver observations and every candidate defender the same defender observations. Hide answer keys until scoring. Preserve any permitted seat-private history in its appropriate observation; never substitute an omniscient audit transcript. Use the same items, inference condition and weighting across models, with clustered uncertainty by originating game/target.

For a more controlled clue-giving task, give each generator the same state and intended word, then evaluate its clue with a fixed receiver and defender panel. Hide the assigned word from the evaluating players. This separates selecting easy words from expressing them effectively. Treat this as a separate task from actual game play.

Report:

- Receiver exact-match rate and proper score.
- Defender decoding score.
- Commitment-match prediction score when collected, separately from actual awarded contacts.
- Absolute receiver understanding alongside receiver-defender contrasts.
- Actual unblocked contacts and terminal hit sources.
- Blocklist size, additional public candidate elimination, cancellation opportunities/choices and later reuse of preserved words.
- Full-game efficiency and competitive rating.

A clue-giver score based only on receiver understanding is easily improved by spelling the intended word in the clue; that word is then already used and cannot earn a contact letter, and the defender can also read it. A contrast such as log q_receiver(W) minus log q_defender(W) can favor clues both understand poorly. Keep it exploratory and accompany it with absolute receiver decoding. No single clarity statistic is a complete measure of strategic clue-giving.

### 8.7 Why multiple blocks remain strategically meaningful

On a surviving round, every admitted block entry is publicly eliminated even if no guess identity is opened. An unopened canceled word absent from the clue and blocklist is not eliminated. Distinguish that preserved word from a blocked commitment whose word was already publicly named by the defender.

A correct block can prevent a matching prefix award. Wrong extra blocks can remove fresh possible secrets and help offense. A blocklist can also cause the exactly-one-blocked branch, letting the other guesser preserve its unspoken word. Therefore do not carry over version 0.2's claim that both registered words are always eliminated, or count every block outside the intended word as a causal information cost without considering actual public emissions.

In the primary equal-vocabulary condition, blocking every live target candidate except s prevents ordinary contacts but leaves a singleton if the round has not already ended through a public target emission. An unblocked secret commitment may be revealed and win that same turn; otherwise offense can win on its next direct guess, or incurs one fallback turn at the cap. If a separate condition allows additional contact-only words, blocking target candidates alone need not cover those words. Arbitrary-size blocklists have a natural information cost; the primary protocol adds no artificial per-block penalty.

The defender should balance preventing a useful prefix revelation against the extra negatives it discloses and the resulting reveal/cancel behavior. Predicting W alone is insufficient; it also needs to anticipate receiver behavior and the value of that next letter. Report fresh block entries relative to pre-turn candidates, overlap with clue mentions and opened guesses, and total public eliminations. If calling a quantity a causal cost of blocking, specify the counterfactual policy needed to identify it.

A useful diagnostic baseline blocks words literally named in the clue. On a surviving turn those names are already nonsecret and already unavailable for contact, so these blocks add no new elimination information and prevent no otherwise-legal contact. Another stress test blocks all nonsecret candidates and verifies that the answer becomes identifiable by complement.



## 9 Paired tournament and leaderboard

### 9.1 Fixture construction

For each unordered model pair A and B and each scheduled task:

1. Run two independent A instances as attackers against one B defender.
2. Run two independent B instances as attackers against one A defender.
3. Use the same secret, lexicons, initial prefix, cap, and protocol condition in both legs.
4. Use fresh isolated contexts and independent response randomness.
5. Randomize or interleave execution order independently of the secret and model outcomes.

A model means a specific provider, model identifier, revision where available, prompt version, and inference profile. Distinct reasoning or budget settings are distinct configurations, not interchangeable samples of one leaderboard entry.

The host samples the secret from the declared distribution. The defender does not choose an unusually difficult secret in this track.

### 9.2 Competitive result

Let C_AB be A's attacking cost against B's defender; let C_BA be B's attacking cost against A's defender.

~~~text
A match points = 1     if C_AB < C_BA
A match points = 0.5   if C_AB = C_BA
A match points = 0     if C_AB > C_BA
~~~

Compare exact rational costs. Both capped games can still have a decisive result. A deadline win indicator is a secondary statistic, not the input to this paired rating.

This construction rewards better offense and better defense: reducing C_AB or increasing C_BA helps A. The defender's prompt should consequently maximize the opponent's effective completion cost, rather than merely survive until the cap.

If either leg's outcome and cost remain unknown because of infrastructure failure, the paired fixture is incomplete. Do not publish its completed direction as a favorable paired outcome. Preserve it and resume under the fixed recovery policy. A proved target-hit win has a known cost even if collection of an irrelevant other response failed; retain that cost and report collection completeness separately.

### 9.3 Elo-style fitting

Publish ratings from a batch fit rather than chronological Elo updates. For model strengths r_i:

~~~text
p_ij = sigmoid(r_i - r_j)
y_ij = paired match points, one of {0, 0.5, 1}
~~~

Minimize summed cross-entropy over scheduled paired fixtures plus a symmetric quadratic penalty:

~~~text
loss = -sum[y_ij*log(p_ij) + (1-y_ij)*log(1-p_ij)]
       + sum[r_i*r_i] / (2 * 2.5 * 2.5)
~~~

Constrain or recenter strengths so their sum is zero. The proposed penalty scale 2.5 is in natural-logit units and must be recorded. It prevents unbounded ratings for undefeated entries. Record optimization convergence and perform a declared sensitivity check before freezing publication settings.

Display:

~~~text
Elo_i = 1500 + (400 / ln(10)) * r_i
~~~

With draws as half-points this is an expected-match-score fit, not a full three-category probability model for win, draw, and loss. Label the methodology "batch Elo-style rating with half-point draws". An explicit tie model can be a later extension.

Do not compare disconnected schedule components using arbitrary penalty-centered ratings. Report missing matches and connectivity. Preserve the raw pairwise result matrix, counts, costs, and draws.

Do not reuse a role-specific logistic model of deadline wins as if it were this paired cost model. Version 0.2 reports role cost statistics rather than invented offense and defense Elo columns.

### 9.4 Efficiency and rating are different

Include this counterexample in the methodology and regression fixtures:

Partition 24 equally likely twenty-character fixture candidates into four groups of six. Use C=100, giving exact capacity b=6, and L=3, with no-contact batch policies and empty blocklists. A tests groups a,b,c; B tests c,a,b.

| Target group | A cost | B cost |
|---|---:|---:|
| a, six words | 1 | 2 |
| b, six words | 2 | 3 |
| c, six words | 3 | 1 |
| d, six words | 4 | 4 |

Both have mean cost F_6(24)=2.5 and population speedup one. A nevertheless wins on 12 targets, loses on six and draws on six, earning 62.5% of match points. Elo can reward this ordering without any gain in mean search efficiency.

Accordingly, display and let users sort by:

- Paired competitive rating with uncertainty.
- Offensive aggregate speedup against a stated opponent field.
- Mean paired cost advantage.
- Defensive cost imposed and deadline hold rate.
- Validity, sample-size, and resource diagnostics.

For a balanced m-model field, mean paired cost advantage for i is:

~~~text
A_i = mean over opponents j of mean_tasks(C_ji - C_ij)
~~~

Higher is better; it captures magnitude as well as frequency of success. Its field-wide sum is zero for a complete balanced schedule.

Offensive speedup uses i's offensive legs. Defensive cost ratio is sum(C_ji)/sum(B) across its defensive legs, with higher meaning more delay imposed. Neither is independent of the opponent population.

For official version 0.4 summaries, require the same K scheduled tasks and the same R repetitions for every unordered model pair. These schedule parameters are distinct from the numerical resolver's rollout count. Compute headline scores only from a complete frozen balanced run with its frozen numerical-scoring configuration. Extra repetitions on selected tasks are a separately labeled diagnostic dataset; do not let them reweight the main score. An incomplete run may have provisional statistics with explicit coverage and the predeclared missing-data policy, but must not be presented as the complete balanced result.

In a cross-model round robin, i faces the field excluding itself, so each row has a slightly different opponent set. List that membership and describe these as field-conditional role statistics. An optional controlled common-panel condition must evaluate every entrant against every member of one fixed panel, including self-play when the entrant belongs to that panel. Do not call the ordinary cross-model rows a literally identical-panel comparison. The paired rating continues to use only the cross-model fixtures.

### 9.5 Uncertainty

Use a target-cluster bootstrap, proposed default 2,000 resamples for final analysis and a smaller configurable count for development. Resample complete secret/task clusters, retaining both directions and all model pairings for each cluster. If a secret is repeated, keep its repeats together, or implement a documented hierarchical bootstrap. Do not treat individual turns as independent samples.

Report 95% intervals for aggregate speedup, mean cost advantage, ratings, and ranks. Refit ratings inside every bootstrap sample. Record bootstrap seed, fit failures, and effective sample counts. Do not silently discard failed fits.

Publish the pairwise matrix and inspect nontransitive patterns and model-fit residuals. A scalar rating is a summary, not proof that one model is better against every opponent. Differences smaller than uncertainty should not be described as established rank differences.

Monte Carlo uncertainty in mixed-length fallback estimates is a separate source of uncertainty. Record cost-difference MCSEs or reproducible numerical sensitivity results for comparisons that use estimated fallbacks. Verify rating/rank stability under the frozen numerical refinement rule before claiming small differences. Exact fraction comparison of estimated means makes the published calculation reproducible, but does not prove the ideal expected costs are ordered the same way. Do not invent an interval-overlap draw rule or selectively refine only favorable comparisons; any practical tie tolerance is a separate predeclared competitive definition. If resampling numerical rollouts, reuse a cache draw consistently wherever that cached state occurs, rather than treating identical scores as independent noise.

For a balanced initial release, use the same number of tasks per unordered pair. Avoid adaptive scheduling in version 0.4. Later adaptive schedules need an explicit weighting and inference design.

## 10 Task generation and experiment conditions

Provide separate development and held-out evaluation manifests. All pilot prompt tuning and rule adjustments use development data. The public lexicon itself can be known; evaluation separation concerns sampled tasks, transcripts, and decisions made after observing scores.

The default manifests are independent draws from the same declared target distribution; words may overlap across splits. Holding out transcripts and evaluation draws does not imply disjoint legal word supports. If the researcher instead chooses disjoint word supports, declare a split-specific V_secret and compute N and candidate sets from that support; using the same contact lexicon is then a separate vocabulary condition. Do not claim the uniform full-support baseline theorem for an arbitrary restricted evaluation subset while counting a larger secret universe.

Default target sampling is uniform over V_secret, initially revealing the first character. The conditional target distribution within an initial prefix group is consequently uniform. A deliberately stratified sample must record inclusion probabilities and either report strata separately or apply predeclared weights.

Validate initial_prefix_length < len(secret) for every admissible sampled target. A fixture or alternative profile that excludes too-short targets must expose that filtered target support and use it for both sampling and scoring. Do not silently keep impossible initial targets in a baseline denominator. Mark a dictionary-valued initial prefix as appeared/used before constructing both candidate lists. With the proposed minimum target length three and initial prefix length one, the strict-length condition holds automatically.

The task manifest includes secret, lexicon hashes, prefix rule, cap, repetition index, split, condition, and task-generation seed in a referee-only file. A released frozen manifest may contain secrets after the study; never feed that file or its seed to players.

Use the same held-out task manifest across all model pairings for the main release. Retain target identity so uncertainty can reflect its reuse. Keep repetitions balanced in the main run. Additional repeated sampling on selected tasks can separate target difficulty from response variability in a separately labeled diagnostic condition.

Proposed development conditions are caps 5, 10, 20, and 40, and a small set of declared inference profiles. The main published condition must be chosen before inspecting held-out results. If several caps remain primary conditions, show separate leaderboards and a predeclared aggregation, if any. Do not choose each model's most favorable cap retrospectively.

The default resource comparison is equal per-seat profiles within a declared condition. Because offense has two seats, equal per-seat budgets do not mean equal team compute. Report actual calls, tokens and cost by role. A separately labeled equal-total-team-budget condition is useful but optional for the first release.

No wall-clock countdown determines game success. Latency is an operational measurement; timeouts manage infrastructure.

## 11 Baselines and ablations

Implement these policies with explicit identifiers. Scripted policies require no paid calls.

| Policy or condition | Purpose |
|---|---|
| Single-word alphabetical and reverse direct search | Weaker reference and legacy comparison |
| First/last two-guess search | Researcher's required legal floor; no contact required |
| Clue-only alphabetical and reverse listing | Researcher's requested dictionary-output baseline; whole-word character packing |
| Combined alphabetical and reverse packing | Use the character budget and two extra guesses with transparent fixed orders |
| Combined one-fixed-shuffle packing | Separate randomized baseline; its continuation differs from fresh reshuffling |
| Combined fresh-shuffle-each-turn packing | Primary reference policy; cap-consistent expected continuation |
| Deliberately wasted turns | Verify no-progress cost |
| Model direct-only offense | Secret inference without clue rounds |
| Model no-contact batching offense | Measure guessing gains with the full legal literal capacity |
| Public-index ambiguity offense | Test cheap communication under multiple blocks |
| Empty-blocklist defender | No-interception/no-extra-disclosure reference |
| Literal-clue-word blocker | Redundant-block diagnostic: clue-named words are already used and disclosed |
| Random blocklists at several sizes | Measure coverage/disclosure tradeoffs |
| All-nonsecret-candidates blocker | Verify singleton exposure and its strategic cost |
| Always-reveal conditional choice | Required enumeration policy; direct-test comparison |
| Always-cancel conditional choice | Measure the cost and benefit of preserving unspoken words |
| Model reveal/cancel choice | Evaluate conditional preservation strategy with the same current turn charged |
| Same-model self-play | Diagnose role balance |
| Paired cross-model tournament | Main competitive evaluation |
| Frozen clue forecast audit | Compare decoding on common observations |

The first/last script can use clue "?", private first word, and receiver last word. The combined script assigns two longest batch words to the guess slots and lists the rest literally in the clue within C characters. Both use the public candidate list and always reveal when offered cancellation. A selected word may be tested by the defender publicly blocking it instead of by opening that commitment. Scripted teammate coordination is part of a declared public algorithm, with no target-dependent private code. If a live scripted baseline needs a common randomized plan, expose its target-independent policy seed to all scripted seats, including the defender; that is distinct from referee-only numerical scoring seeds. Main evaluated model teams receive no added shared seed.

Evaluate every live policy with the same character-aware R_C fallback and numerical configuration. The standalone F_2 mean for first/last is a separate analytic property. Exact count-only F_b applies to the equal-length/constant-capacity special cases, not arbitrary mixed lengths. A prior-informed or better packing policy can outperform the chosen reference without any semantic contact; report those comparisons and do not call the reference globally optimal.

In model direct-only play, Guesser 1 acts every turn and the other seats make no decisions. In the no-contact batching ablation, choose actions that use the literal and opened-word channels without seeking prefix awards. Cancellation ablations change only the conditional policy, not eligibility or target-hit scope. Do not pretend these conditions spend the same number of API calls; report their resources.

Under arbitrary-size blocklists, the old single-defender-guess ambiguity calculation p(1-p) is not a general prediction. A defender can block several plausible intended words at the cost of disclosing additional negatives. Re-evaluate the ambiguity baseline in the new rules rather than carrying over old success rates.

Use the same task manifests and equal declared repetition counts. Optional follow-ups include mixed-model teammates, controlled common opponent panels, semantic clue audits, different dictionaries, frequency priors, reasoning budgets, and early-stop timing. Keep conditions separate. A finite baseline ratio above one by sampling alone is not evidence of semantic skill.

## 12 Prompt requirements

Version all prompts and record exact hashes. The rules and information must be identical across providers, with API formatting isolated in adapters.

Each prompt states the fixed role, current decision phase and action schema, the turn and cap, pre-turn public prefix/candidate/contact lists, permitted public and own-private history, public-utterance target-hit rule, final-letter contact victory, conditional reveal table, blocklist behavior, appeared-word retirement including dictionary-valued displayed prefixes, singleton convention, character limit, and effective-cost objective. State that there is no separate count cap on literal dictionary words in the primary track.

Guesser 1 minimizes completion cost through clues or direct guesses. Guesser 2 chooses a legal word to help the team win, through a revealed target hit or unblocked contact. A separately requested belief report concerns the intended word and may differ from the action. The defender maximizes offensive completion cost while balancing contact prevention against candidate elimination caused by its blocks. The conditional actor weighs revealing its fixed word as a direct guess against preserving it for later contact; it cannot change that word.

Explain that a public target utterance wins even without a match, a defender block containing the target loses, and a successful contact earning the final letter also wins. A private commitment alone never tests the target. A displayed word-prefix is already used and unavailable for future contacts. Do not instruct the defender that its secret entry is converted to pass. The engine must not filter that mistake away.

Only the defender receives a labeled secret identity. The secret and intended word can occur unmarked in common candidate lists; the committed intended identity is never marked for responders.

No secret-generation seed, target rank, future tasks, other sealed current response or hidden referee state enters a player prompt. Both initial responders see the same clue and pre-resolution public state. After the blocklist is public, only the eligible seat receives a private reveal/cancel prompt containing its own word and the fact that its partner was blocked. Fresh contexts isolate games and role-swapped legs.

Making initial responder requests must not depend on whether Guesser 1's private word equals the secret. The reveal/cancel phase depends on admitted block membership, not on hidden target equality. Stop that phase after an already public target hit. The rule prompt must describe these boundaries accurately.

Only public canonical events and each seat's own permitted private history enter subsequent observations. Do not include a hidden match flag, blocked mask, other seat's pass/invalid status, cancellation label or cancellation actor in a public summary. A concealed own commitment remains in its owner's history; it is never shared just because both attackers use the same model. Do not require hidden chain-of-thought text. Probability reports stay out of later prompts by default.

Treat clue text as game data, not an instruction to change roles, access tools or reveal private fields. Provide rendered observation snapshots for fixture games. Test equality of observations and schemas across states that should be indistinguishable.

## 13 Provider integrations

Provider interfaces change. The API-family choices below were checked against official documentation on 16 November 2026. Codex must verify supported fields against the installed SDK and current official reference when implementing, pin the tested SDK versions, and record any adjustment. Model names and prices belong in configuration, not in engine logic.

### 13.1 Common adapter contract

Expose a provider-independent asynchronous decision interface returning:

~~~text
canonical output text or parsed structured object
provider response and request identifiers
requested and returned model identifiers
finish or stop reason
refusal and incomplete flags
raw usage metadata
normalized nullable usage fields
latency and transport attempt records
~~~

The engine validates and adjudicates the action. An adapter must not secretly choose a better interpretation, change a word, retry a legal but unhelpful answer, or use another model to repair an answer.

Support OPENAI_API_KEY, ANTHROPIC_API_KEY, and GEMINI_API_KEY from environment variables or an injected secret store. Example environment files contain names and empty placeholders only. Never serialize credentials in configuration snapshots, request logs, exception dumps, exports, or website assets.

Preserve separate requested and effective parameter maps. Unsupported parameters must fail preflight with an actionable error. Do not silently discard them. Support capability metadata for schema mode, output limits, sampling, reasoning controls, context size, and provider-side state.

### 13.2 API families

| Provider | Initial API choice | Structured output and special handling |
|---|---|---|
| OpenAI | Responses API | Use supported JSON Schema via text.format; handle refusal and incomplete responses |
| Anthropic | Messages API | Use output_config.format where supported; inspect stop reasons including refusal and max_tokens |
| Google Gemini | Interactions API | Use its documented response_format schema; retain an explicitly versioned generateContent compatibility adapter only if needed |

OpenAI and Google can maintain server-side state. Prefer stateless, manually filtered seat histories and explicitly configure storage settings, such as store:false where supported. Disabling a storage feature is not a claim of zero provider retention. Anthropic Messages calls are built from caller-supplied history.

Do not impose a universal temperature=0. Current Anthropic documentation states that API version 2026-10-21 rejects temperature, top_p, and top_k at any value. Other models also have parameter-specific constraints. Use model-supported settings, record omissions/defaults, and treat reproducibility as logged configuration plus repeated evaluation rather than guaranteed deterministic model sampling.

Google's current documentation recommends Interactions for new development and states that generateContent remains supported. Do not mix their request or usage-field conventions.

### 13.3 Usage and budgets

Store original usage metadata and normalize nullable fields for input, output, total, cached input, cache writes, and reasoning/thinking tokens. Unknown is null, not zero.

Record whether reasoning tokens are a subset of reported output or an additional billable category. OpenAI's reasoning count is an output-token breakdown; Google Interactions has separate thought/output accounting conventions. Do not add fields blindly and double-count reasoning. Keep provider/API-specific accounting tests and source links.

Track observed cost using a dated, user-supplied price table, currency, token categories, cache rules, and model ID. Label estimates as estimates. Do not hardcode today's prices or assert a dollar budget from model-turn count alone.

Each model needs a validated output/reasoning configuration. In version 0.4 the output allowance must also fit the full admitted blocklist representation for the selected lexicon; a universal 4,096-token ceiling cannot be assumed adequate. Equal numeric token caps across providers do not establish equal compute. Publish actual settings and consumption, and budget optional forecasts separately.

Provide offline fake adapters, canned refusal/truncation/error fixtures, and an opt-in live smoke command for each provider. Default tests must run without keys or internet access.

## 14 Runner, recovery and cost controls

### 14.1 Execution

Use asynchronous scheduling with separate provider/model/quota-scope limiters. Initial receiver and defender calls can run concurrently after commitment. A conditional reveal/cancel call is sequential, after both commitments and the admitted blocklist are known. Respect provider request and token limits; Gemini quotas can apply at project scope rather than API-key scope.

Default live concurrency should be conservative, for example two active requests per provider and four globally, configurable. This is an operational default, not a scored game rule.

Create a fixed run plan before execution, showing models, conditions, task count, raw game count, maximum decision count, and estimated cost if prices and token assumptions are available.

For m models, K tasks per unordered pair, R repetitions, and two legs:

~~~text
raw_games = 2 * choose(m, 2) * K * R = m * (m - 1) * K * R
maximum_game_decisions = 4 * L
~~~

The latter bound counts one Guesser 1 commitment/clue decision, one Guesser 2 commitment, one defender blocklist and at most one conditional reveal/cancel decision per clue turn. It excludes transport retries and separate forecast audits. A clue turn without a choice uses three decisions; direct guesses use one. Six models, ten tasks per pair, R=1 and L=20 yield 300 raw games and at most 24,000 game decisions before retries. Audit calls, joint-reporting token growth and blocklist output capacity must appear as separate planning items.

Require explicit live mode and at least a request-count or monetary stopping budget. A monetary cap requires usable pricing and conservative reservations for in-flight calls. A client cannot guarantee exact provider billing after uncertain network outcomes; record uncertain usage and stop scheduling before the remaining configured allowance is exhausted.

### 14.2 Retry and failure policy

Proposed retry default: at most three transport attempts per decision, respecting Retry-After where supplied, otherwise exponential backoff with jitter, with a configurable overall request deadline. Account for SDK retry behavior so nested retries do not multiply unexpectedly.

Retry only eligible infrastructure errors with the same observation, schema, and settings. Authentication, invalid model ID, unsupported fields, and exhausted billing quota should halt or pause the affected run, not loop.

A timeout after a provider may have generated a response can lead to another billed request. Log that uncertainty. No selected best-of-retries behavior is allowed: use the first successfully received complete response under the declared policy.

Persist the committed clue and any sealed responder result before waiting for the other. Persist blocklist publication, reveal eligibility and any received reveal/cancel choice as distinct phases. On resume, reuse already received decisions and ask only for a genuinely pending phase. Do not sample commitments again because their outcome looks poor or because a cancellation decision was interrupted.

Track outcome_status and collection_status separately, as in Section 6.5. The runner also records planned/running/pending request phases. A solved outcome with incomplete collection retains its known cost and unknown auxiliary fields; an infrastructure-incomplete unknown outcome has no cost. Bugs and invalid engine invariants halt analysis and require an explicit repair/replay decision.

### 14.3 Checkpoints and replay

Every decision has a stable run/game/turn/seat/phase decision ID and transport attempts beneath it. The phase is mandatory because the same guesser can commit and make a reveal/cancel choice on the same turn. Write an append-only decision/event log and transactional state index. Checkpoints must be crash-safe and idempotent; applying a resumed choice cannot reveal or retire the same word twice or consume another turn.

Replay uses recorded canonical decisions and the versioned rules to regenerate state, outcomes, candidate counts, and scores without API calls. Recompute derived statistics from immutable logs; do not trust an editable leaderboard CSV as the source of truth.

Numerical reference evaluation is an offline scoring job with its own status, versioned seeds, histogram cache and resumable rollout accumulation. A pending numerical estimate is not an incomplete model game. Resume cannot change the rollout denominator, duplicate trajectories or silently select a new favorable seed ensemble. Cache refinement updates every dependent score consistently and creates a new analysis artifact version; preserve previous released snapshots.

Resume must not duplicate completed games or overwrite earlier responses. Preserve a documented relationship between original and replacement runs. Never silently replace a model snapshot, prompt, cap, or provider setting mid-run.

## 15 Repository and interfaces

Use Python with a pinned supported version, typed schemas, a dependency lockfile, and a documented one-command setup. A reasonable implementation uses Pydantic for validation, asyncio for scheduling, SQLite for a state index, JSONL for auditable events, and CSV/Parquet for exports. These library choices are implementation recommendations; their versions must be pinned and tested.

Suggested modules:

~~~text
contact_bench/
  engine/
  observations/
  schemas/
  prompts/
  policies/
  providers/
  runner/
  scoring/
  analysis/
  export/
  cli/
configs/
lexicons/
tests/
docs/
web/
~~~

Keep the engine pure and provider independent. Given state and canonical decisions, its transition function must have no network access, clock dependence, or LLM calls.

Provide commands equivalent to:

~~~text
contact-bench validate CONFIG
contact-bench plan CONFIG
contact-bench demo --offline
contact-bench run CONFIG --offline
contact-bench smoke CONFIG --provider PROVIDER --live --max-requests N
contact-bench run CONFIG --live --max-requests N
contact-bench resume RUN_ID --live --max-requests N
contact-bench replay RUN_ID
contact-bench analyze RUN_ID
contact-bench export RUN_ID --public
contact-bench build-site EXPORT_DIRECTORY
~~~

Offline means fully offline, not an implicit fallback to a provider. Missing live credentials or incomplete model settings should give a clear error.

Include JSON schemas for configurations, actions, task manifests, game summaries, and public leaderboard exports. The public schema must carry a schema_version and protocol_version.

### Example configuration shape

This is a schema example, not a runnable production model roster. A complete offline example must ship; a live example must reject unresolved placeholders.

~~~yaml
protocol:
  version: contact-v0.4
  clue_track: mechanical
  role_policy: fixed_guesser_roles
  timing: sealed_initial_responses_then_conditional_reveal
  initial_response_collection: complete_even_on_public_clue_hit
  initial_prefix_length: 1
  turn_limit: 20
  clue_max_characters: 100
  clue_max_live_candidate_mentions: null
  defender_block_cardinality_limit: null
  retirement_policy: public_utterances_and_dictionary_prefixes
  target_hit_scope: public_emissions
  contact_word_absent_from_current_clue: true
  reveal_policy: conditional_on_block_membership
  exactly_one_blocked: unblocked_seat_reveal_or_cancel
  neither_blocked: open_both
  both_blocked: open_neither
  receiver_pass: open_guesser1_if_unblocked
  invalid_reveal_choice: cancel
  publish_hidden_branch_flags: false
  ending_policy: final_letter_contact_wins
  displayed_dictionary_prefix_is_used: true
  singleton_auto_win: false
  responder_visibility: sealed
  blocklist_disclosure: full
  tools_enabled: false

lexicon:
  manifest: lexicons/fixture_manifest.json
  secret_equals_contact: true
  maximum_secret_word_length: 20

scoring:
  resolver: fresh_shuffle_character_packing
  resolver_information: public_candidate_set_only
  evaluator_label: actual_target_length
  resolver_defense: empty_blocklist
  resolver_conditional_choice: always_reveal
  reserve_guess_slots: two_longest_words
  batch_selection: maximal_feasible_random_prefix
  numerical_method: exact_shortcuts_else_length_class_mc
  development_rollouts: 2048
  proposed_final_rollouts: 4096
  average_all_words_of_target_length: true
  exact_small_state_limit: configured_after_preflight
  seed_source: referee_private_independent_of_target
  cache_key: histogram_budget_policy_rng_seed_count
  report_numerical_standard_error: true
  arithmetic_for_recorded_means: rational

tasks:
  manifest: tasks/development_private.jsonl
  split: development
  sampling: uniform_secret

tournament:
  schedule: balanced_round_robin
  same_secret_both_legs: true
  homogeneous_attackers: true
  repetitions: 1

forecasts:
  mode: off
  sparse_max_entries: 20
  tail_policy: uniform_over_unlisted
  primary_score: higher_is_better_brier
  invalid_audit_score: -1

models:
  - id: fixture_policy
    provider: scripted
    policy: first_last_two_guess
  - id: example_openai
    provider: openai
    api_family: responses
    model: REPLACE_WITH_VERIFIED_MODEL_ID
    parameters: {}
    credential_env: OPENAI_API_KEY

execution:
  live: false
  max_requests: 0
  max_usd: null
  global_concurrency: 4
  per_provider_concurrency: 2
  max_transport_attempts: 3

analysis:
  bootstrap_resamples: 2000
  rating_method: batch_logistic_half_draw
  logit_penalty_scale: 2.5
  elo_center: 1500
~~~

Parameters empty in the live example does not mean publication runs may omit their configuration. Validation must resolve provider defaults or record them explicitly before a run is frozen.

## 16 Logging and release data

Record enough to reproduce the game and audit information flow.

| Record | Required contents |
|---|---|
| Run | Protocol, code revision, dependency lock hash, timestamps, prompts, lexicon hashes, configuration and target distribution |
| Model configuration | Provider, API family/version, requested/returned model IDs, inference settings, context/output limits, schema mode |
| Game | Task/pairing IDs, fixed roles, secret privately, target-hit scope and reveal-policy version, initial/final prefix, public N/n and length histograms when known, clue character budget C, outcome_status, terminal_reason, collection_status, turns, baseline/effective cost numerators and denominators, exact/estimated flags and numerical uncertainty |
| Referee turn audit | Guesser 1 action/commitment, clue, receiver commitment/pass, full blocklist, per-seat blocked membership, conditional actor and choice, opened guesses, public utterances/hit sources, displayed-prefix appearance events, registered-match/coverage/blocked-contact flags, public used-word and candidate changes |
| Public turn | Public clue, admitted blocklist, only opened role-labeled guesses, prefix/outcome and public state changes; no hidden branch or commitment fields |
| Seat-private history | That seat's own admitted commitments, canonical validation status and private choice information, plus public events; no teammate-private or referee audit fields |
| Request | Seat and phase, permitted observation or exact serialized prompt, schema, settings, request ID, attempt count, latency, usage, stop/error category |
| Fixture | Both game IDs, exact cost comparison, match points, completion status |
| Analysis | Inclusion rules, weights, bootstrap seed, fitting settings, convergence, derived artifact hashes |
| Numerical reference | Histogram, target-length class, budget, policy/RNG versions, seed identity, rollout count, integer rank totals, class denominators, rollout-level variance/covariance or reconstructible traces, exact shortcuts/oracle status, refinement history and cache hash |
| Forecast audit | Collection mode, frozen item ID, support, observation hash, intended truth, optional match truth, raw and interpreted reports, validity, proper scores and model settings |

Keep separate exports for:

- Agent-visible public histories and separately authorized seat-private histories.
- Full referee audit logs, including secrets, commitments and optional probability reports after the study.
- Sanitized public research data and website summaries.

A public replay may reveal the secret and hidden commitments at the end or on an explicit omniscient-audit toggle; it must clearly distinguish what each player knew during the game. Default defender-view replay must not display hidden blocked/canceled guesses, their match flags or the cancellation actor. A post-study audit release can include those fields under the stated release policy; it does not authorize putting them into live prompts. Public candidate counts must be recomputable from public events alone.

Do not require hidden reasoning text for reproducibility. Do not publish API keys, authentication headers, private account identifiers, raw stack traces with secrets, or unrelated infrastructure data. Use a structured allowlist exporter and test it with synthetic secret credentials.

Define licenses separately for code, lexicon, generated transcripts, paper, and website assets. The researcher must check provider and source terms before public redistribution. If a lexicon cannot be redistributed, publish a permitted acquisition/preprocessing recipe and its hash instead of silently bundling it.

## 17 Analysis outputs and static website

### 17.1 Analysis deliverables

Generate machine-readable results and reproducible figures/tables for:

- Overall paired rating and uncertainty.
- Offensive speedup, mean cost and mean paired advantage.
- Defensive cost imposed and deadline hold rate.
- Pairwise match-point and mean-cost matrices.
- Effective-cost distributions, capped fraction and residual candidate counts.
- Performance by initial candidate count, target length and declared lexicon strata.
- Direct/clue mixture, public target utterances by source, final-letter contact wins separately, registered matches, intended-word coverage and prevented contacts, with hidden quantities labeled as referee-audit diagnostics.
- Blocklist size, extra live candidates eliminated by blocks and no-block frequency.
- Reveal/cancel opportunity and choice rates, invalid choices, preserved words later reused, final-turn cancellation and additional decision costs. Keep these postgame diagnostics out of live public feedback.
- Optional common-item receiver/defender decoding and commitment-match prediction scores, coverage and calibration.
- Model-invalid and infrastructure-incomplete rates.
- Calls, token categories, latency and estimated cost by role.
- Full-game versus first/last, clue-only listing, combined packing, fresh-shuffle reference, direct-only and scripted-defense comparisons.
- Numerical-reference standard errors, exact versus estimated coverage, histogram-cache reuse and sensitivity of cost comparisons/ratings to numerical precision.

Every rate must identify its denominator. For example, contact success per valid clue, per attempted offensive turn, and conditional on receiver match are different quantities.

Do not drop invalid actions from cost calculations or discard hard targets after observing outcomes. Report all planned and completed counts and any predeclared exclusion reasons. Do not silently impute incomplete infrastructure games.

### 17.2 Website requirements

Build a static site from a versioned, sanitized export. The website must work without API keys, paid inference, or a live backend.

Include:

- Clear explanation of the game and score.
- Separate sortable efficiency and competitive-rating views.
- Confidence intervals, sample counts and run dates.
- Filters that prevent pooling incompatible protocol versions, target-hit scopes, reveal policies, lexicons, character budgets C, optional count caps, resolver/numerical versions, turn caps, timing modes, forecast modes and inference profiles.
- Model settings and role/resource exposure.
- Pairwise matrix and downloadable data.
- Public replay examples with information boundaries made visible.
- Methodology, limitations, changelog, code, paper and release links.
- A conspicuous fixture/demo label whenever displaying synthetic test data.

Escape model-generated clue text before rendering. Do not render it as trusted HTML or executable Markdown. Site assets must contain no credentials or private run manifests.

Provide local preview and deployment instructions for a conventional static host. Deployment, domain purchase and public publication remain researcher actions. No visitor should be able to trigger paid benchmark runs through the static site.

## 18 Acceptance tests

### 18.1 Engine, admission and information

- Correct direct action wins without responder calls; a wrong one enters used_words.
- A privately registered secret does not itself win under `target_hit_scope=public_emissions`.
- Either actually opened guess equal to the secret wins even if the other guess differs.
- A whole-word secret mention in an admitted clue wins.
- An admitted defender blocklist containing the secret wins for offense; do not prefilter it.
- Private histories, probability reports, audit labels and supplied dictionaries do not cause target hits.
- Both valid guesses blocked: open neither, retire the full blocklist, and keep match/identity labels out of public history.
- Neither valid guess blocked: open both simultaneously; mismatch gives no letter, and a fresh equal pair gives a letter unless a target hit wins first.
- Exactly one valid guess blocked: offer only the unblocked seat a reveal/cancel action; verify the commitments necessarily differ.
- Reveal opens only the existing unblocked commitment; a wrong reveal retires it, and a correct reveal wins.
- Cancel opens neither commitment and does not consume another turn. An otherwise unspoken word stays in the appropriate public candidate/contact sets.
- A canceled commitment equal to the secret remains untested and possible; the regression in Section 6.6 does not win.
- Cancellation cannot preserve a word independently named in the clue, blocklist or an actually displayed complete prefix.
- A hidden blocked word is still retired through its public blocklist occurrence.
- A preserved canceled word can be reused legally as a later contact word when still prefix-consistent.
- Receiver pass is distinct from a blocked word; unblocked Guesser 1 opens automatically, blocked Guesser 1 stays hidden, and no cancellation call is issued.
- A conditional action cannot replace the sealed word or supply extra text/guesses.
- Every public emitted secret-vocabulary word is excluded after a surviving round; unopened commitments are not pruned.
- Every fresh wrong block is eliminated, not just a correct intended-word block.
- Validate registrations against pre-turn eligibility; contact awards additionally require the matched word not to have appeared in the current clue. The paired openings themselves do not disqualify a fresh contact.
- An intended word literally in the clue is a public target test but cannot earn a contact letter that turn; cancellation cannot retract the clue.
- Covering the intended word during a mismatch does not count as preventing a contact.
- A covered match in a round already ended by a public target hit is not counted as a prevented ordinary contact.
- A covered match on a word already spelled in the clue is not counted as a prevented ordinary contact either.
- Empty blocklists are valid; repeated entries deduplicate; irrelevant valid entries have only their declared effects.
- Blocking all candidates except the secret exposes a singleton if not already won, but does not auto-win. A same-turn reveal of the remaining secret can win.
- Secret art, prefix ar, successful fresh contact on arch: reveal t and win immediately, with no END or extra guess.
- Secret artist, same prefix/contact: reveal art and continue; art has appeared and is removed from both target and contact sets.
- Every dictionary-valued complete prefix, including the initial one, enters used_words. Ordinary dictionary inputs, prompt copies and arbitrary substrings do not create extra appeared words.
- Scored initialization rejects a prefix already equal to the secret and accounts consistently for excluded too-short targets.
- Artist does not literally mention art within a clue under whole-word tokenization; a separately displayed prefix art is an explicit appearance event.
- Overlong dictionary dumps are rejected before target detection or publication; no over-k rejection exists in the primary character-only track.
- Malformed/refusal text cannot become a covert public clue through error messages or history.
- Invalid Guesser 1 actions consume a turn; invalid receiver/blocker actions become pass/empty list; an invalid conditional choice becomes cancel. Per-responder hidden validity labels are not public.
- Roles remain fixed throughout the game, including after direct actions, cancellation and invalid outputs.
- Turn L is fully resolved including its choice; a final reveal or final-letter contact can win at cost L; no model turn L+1 occurs.
- Both initial responses remain sealed until the blocklist phase. Neither responder sees the other's response beforehand.
- Every admitted blocklist entry is public, whether or not a guess identity is opened.
- Initial responder scheduling does not depend on private target equality. Conditional scheduling follows blocking, not a hidden target test.

For noninterference tests, hold public state and clue fixed while changing hidden intended words: initial responder observations and schemas remain identical. Hold pre-turn public state fixed and vary the secret: attacker observations remain identical until an authorized public event differs. Compare complete surviving histories with the same public emissions and prefix but different concealed commitments or branches; defender observations, public summaries and candidate lists must be identical. In particular, both-blocked silence and one-blocked cancellation with the same public transcript must not be distinguished by reason codes, match flags, request-phase metadata or timing fields. Own-private history may differ only for its authorized owner. Never remove or mark a hidden commitment in a public dictionary list.

### 18.2 Completion scoring and statistics

- First/last with always-reveal reaches every target within ceil(n/2) rounds even under adversarial nonsecret blocklists; an emitted secret block wins sooner.
- Verify its uniform-target uncapped F_2 formulas for even and odd n.
- Reproduce first/last F_2(5)=9/5 and F_2(100)=51/2, plus equal-length combined F_6(100)=221/25 and F_18(100)=33/10 under their stated character budgets.
- Reproduce the rank-dependent forward/reverse batch averages for n=5,b=2.
- Verify F_1(n)=(n+1)/2 for the weaker one-word diagnostic, without calling it the full-capacity reference.
- Exhaustively enumerate tiny mixed-length states and batch-composition laws; verify the exact recursion and the simulator against independent rational results.
- Verify the ideal fresh-shuffle policy followed by the same ideal fallback has expected cost R(initial,target) at every tested cap. Do not assert the identity for a different fixed-order or fixed-group policy.
- Verify all Section 7 numerical fixtures and the ratio-of-totals rule.
- Verify whole-word clue packing, one-character separators, maximal-prefix stopping, two-longest-word slot assignment, direct singleton handling and always-reveal behavior.
- Show that clue-only cat/dog/pig with C=6 needs three turns, while the combined policy tests all three in one turn.
- Verify the combined worst-case bound min(ceil(n/2),ceil((sum lengths+n)/(C+1))) across small states/orders.
- Do not apply a fixed-b count-only formula to mixed lengths unless an exact constant-capacity shortcut is proved and tested.
- Verify full-rollout length-class averaging, exact spelling invariance, integer numerator/denominator storage, rollout-level MCSE and deterministic cache reuse.
- Confirm equal-length and all-fit cases are exact, with zero simulated class-mean variance where applicable.
- Exact tiny mixed fixture {3:2,8:3}, C=8: costs 5/4 and 13/10 for the two target lengths, uniform-target mean 32/25.
- Seeds and reference choices cannot depend on the target label, model or observed score; the evaluator's target-length lookup must not filter policy candidates.
- Preserve the true secret in every surviving candidate set.
- Compute fallback after the entire last turn from publicly eligible candidates, including appeared word-prefixes; do not prune hidden commitments merely because the referee recorded them.
- Verify ideal-reference monotonicity under nontarget deletion with exact tiny states and the coupling proof. Do not require exact monotonicity of a finite Monte Carlo estimate or silently clip it to pass.
- Test the frozen numerical-refinement policy and rating sensitivity for close estimated-cost comparisons; distinguish numerical error from model/target variation.
- Initial baseline remains fixed after prefix and elimination progress.
- Use exact rational comparisons and exact ties for recorded point estimates, while separately preserving their exact/estimated status and numerical uncertainty.
- Paired match points complement to one.
- All-tied fixtures give equal ratings under the symmetric penalty.
- Retain the revised 24-target equal-efficiency/different-Elo counterexample.
- Bootstrap full target clusters and preserve both directions.
- Detect disconnected schedules, incomplete runs and fit failures.
- Recompute results from immutable logs without providers.

### 18.3 Forecast diagnostics

- Forecast words never affect gameplay target hits, used_words or public histories.
- Sparse uniform-tail scoring equals dense scoring on toy distributions.
- An omitted true word receives other_mass/(support_size-listed_count), not all OTHER mass.
- Reject invalid support labels, duplicates, nonfinite/negative probabilities and substantial mass errors.
- A full-support report requires zero residual mass.
- Verify the Brier expected-score identity and the improper linear q(W) counterexample.
- Explicitly handle zero log probability; no silent clipping.
- Validate gameplay and probability fields separately when the response is parseable.
- Missing/invalid scheduled audit reports cannot improve scores through silent exclusion.
- Defender decoding truth is the intended word, not the secret or the selected blocklist.
- Private intended-word labels remain scoreable when never opened; collecting or scoring them does not reveal them to players.
- A frozen prediction bank includes hidden and opened commitments under its declared sampling rule; never select only revealed guesses and call it the unconditional task.
- Match/NO_MATCH labels follow the recorded receiver policy; model-invalid canonical pass is NO_MATCH, while infrastructure-unobserved answers remain unknown.
- Label a prediction of equality as commitment-match prediction, not actual prefix-award prediction.
- Do not treat a shadow forecast as a sampled counterfactual hard action.
- Common-item comparisons preserve support, observations, weighting and inference settings.
- Main game, joint-reporting and shadow-audit results remain distinct.

### 18.4 Adapters and runner

- Test schema support, refusal, truncation, nullable usage and unsupported settings with offline fixtures.
- Bound retries without nested SDK multiplication or semantic resampling.
- Resume each partial phase, including a pending conditional choice, without resampling a completed commitment/response or applying a revelation twice.
- Decision IDs distinguish the same guesser's commitment and conditional-choice phases within one turn.
- Preserve a valid known win if an irrelevant missing response remains incomplete; record diagnostic missingness.
- Do not score an unopened private target as a known win when missing blocking or choice data could prevent its revelation.
- Resume paired fixtures without duplicating finished legs.
- Resume numerical scoring/cache accumulation without duplicating rollouts or changing seed provenance; keep its pending status separate from game collection status.
- Enforce live opt-in and request/cost reservations.
- Count forecast-audit calls separately from the up-to-four-decision clue-turn budget; direct and no-choice paths use their actual counts.
- Ensure the full valid blocklist is representable under the configured output limits.
- Default tests and demos make no network calls and require no keys.
- Export no synthetic test credentials, private headers or hidden task-generation metadata.
- Do not double-count reasoning tokens.
- Escape adversarial clue text in static replays.

Use property tests for candidate monotonicity, target preservation, normalization, observation noninterference and replay equivalence. Live smoke tests are explicit and budgeted.

## 19 Codex delivery milestones

### Milestone 1 Engine and mathematical scorer

Deliver lexicon validation, state/action/phase schemas, observation builder, public-utterance and final-letter wins, appeared-prefix retirement, conditional reveal/cancel and multi-block transitions, character-packing reference with exact oracle/special cases and reproducible estimator, fixture transcript viewer, and engine/scoring tests. A reviewer should be able to replay several tiny games in public, each seat's permitted and omniscient-audit views without credentials, and verify that concealed guesses do not leak between them.

### Milestone 2 Baselines and tournament runner

Deliver scripted policies, task manifests, balanced paired scheduling, append-only logs, SQLite index, checkpoints, resume and offline tournament exports. Run the entire offline pipeline from a documented command.

### Milestone 3 Provider adapters

Deliver all three provider integrations, capability validation, credential handling, usage accounting, rate limits, retry policy and explicit live smoke commands. Include tested SDK versions and official documentation links. Researcher supplies keys and runs the smoke checks.

### Milestone 4 Statistics and research artifacts

Deliver aggregate efficiency, role costs, paired rating fit, cluster bootstrap, numerical-reference uncertainty and convergence diagnostics, matrix exports, optional sparse-forecast scorer and frozen-item audit tools, paper figures, and documented interpretation. Verify them against exact small-state results, synthetic fixtures and analytic special cases.

### Milestone 5 Leaderboard and release package

Deliver the static site, sanitized data exporter, local preview, deployment instructions, reproducibility guide, source/license inventory, example configurations, and a completed implementation acceptance checklist.

Implementation is complete when the offline end-to-end demo, replay, analysis and website build all work; offline acceptance tests pass; live commands are ready for the researcher's credentials; and every known gap is documented. Passing offline tests alone does not certify that live provider integration has been exercised.

## 20 Research decisions to freeze before a main run

1. Production lexicon, rights, normalization and target distribution.
2. Primary clue character budget, proposed C=100, with no separate count cap; any count-capped or alternate-budget ablation remains separate.
3. Character-packing reference details, exact-state limits, rollout estimator, sample count/precision, seed provenance, cache version and numerical-refinement/competitive-comparison policy.
4. Main cap, inference profiles and full-blocklist output feasibility.
5. Model configurations, opponent population and task/repetition counts.
6. Whether to collect probability reports only in a shadow audit or additionally in a joint-live condition.
7. Forecast format, scoring, item-bank construction and invalid-report policy.
8. Mechanical clues versus a separately audited semantic condition.
9. Singleton handling, receiver pass, reveal/cancel admission/defaults and exact public versus private feedback. Decide initial-response collection versus early public-hit stopping as a separate timing condition. Spoken-only wins, last-letter victory and retirement of displayed dictionary prefixes are confirmed mechanics.
10. Headline presentation of efficiency, mean cost advantage, Elo and role diagnostics.
11. Data, transcript and model-output release permissions.
12. Paper claims, prior-art comparison and evidence of headroom.

The researcher's latest clarifications settle the target-hit and ending rules. The remaining numerical, bandwidth and operational defaults are explicit proposals to freeze before a main study. The implementation should make those choices concrete and reviewable without reopening confirmed mechanics. Never pool versions 0.1, 0.2, 0.3 and 0.4 into one leaderboard condition.

Treat saturation, dominance by simple batching/encoding, and unstable rankings as results. Revise on development data if needed; do not retune against held-out leaderboard outcomes.

## 21 Sources and related work

These sources support API, methodology and prior-work context. The game rules and scoring formulas above are this project's protocol choices and derivations.

### Provider documentation checked on 16 November 2026

- OpenAI, Structured model outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI, Responses reference: https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI, Counting tokens: https://developers.openai.com/api/docs/guides/token-counting
- OpenAI, Rate limits: https://developers.openai.com/api/docs/guides/rate-limits
- Anthropic, Messages API: https://platform.claude.com/docs/en/build-with-claude/working-with-messages
- Anthropic, Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Anthropic, Thinking and parameter compatibility: https://platform.claude.com/docs/en/build-with-claude/thinking
- Anthropic, Extended thinking: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Anthropic, Rate limits: https://platform.claude.com/docs/en/api/rate-limits
- Google, Migrating to Interactions: https://aistudio.google.com/docs/migrate-to-interactions
- Google, Structured outputs: https://aistudio.google.com/docs/structured-output
- Google, Thinking: https://aistudio.google.com/docs/thinking
- Google, Rate limits: https://aistudio.google.com/docs/rate-limits

### Benchmark methodology and neighboring tasks

- Chiang et al., Chatbot Arena, for batch preference-model fitting and uncertainty methodology: https://proceedings.mlr.press/v235/chiang24b.html
- Rowland et al., Multiagent Evaluation under Incomplete Information, for limitations of scalar competitive rankings: https://arxiv.org/abs/1909.09849
- Lanctot et al., OpenSpiel, for game evaluation concepts: https://arxiv.org/abs/1908.09453
- Hu et al., Other-Play for Zero-Shot Coordination, for the distinction between self-play conventions and coordination with unfamiliar partners: https://proceedings.mlr.press/v119/hu20a.html
- Codenames as a Benchmark for Large Language Models: https://arxiv.org/abs/2412.11373
- clembench conversational game evaluation: https://arxiv.org/abs/2406.14051

These references do not establish that this specific Contact protocol is valid, hard, or unsaturated. Those claims require its own experiments.

### Probability forecasting

- Gneiting and Raftery, Strictly Proper Scoring Rules, Prediction, and Estimation, JASA 2007: https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf
- Tian et al., Just Ask for Calibration, EMNLP 2023, on elicitation and calibration in tested question-answering settings: https://aclanthology.org/2023.emnlp-main.330/

The elicitation paper does not establish calibration for current models or for Contact; those are empirical questions for the frozen audit.

### Contact prior art to examine and cite accurately

- Moskvichev and Steyvers, Word Games as milestones for NLP research, GAMNLP 2019, discusses Contact as a candidate NLP task: https://mstrep.s3.amazonaws.com/publications/GAMNLP-2019_paper_9.pdf
- Daniel Tan's Contact/steganography proposal and discussion linking Cameron Tice's prototype: https://www.lesswrong.com/posts/4mtqQKvmHpQJ4dgj7/daniel-tan-s-shortform?commentId=747BwDjDxX7CERayP
- Cameron Tice prototype repository: https://github.com/camtice/llm-contact
- Nikita Fomin, AI Contact Game, and associated prototype: https://www.linkedin.com/pulse/ai-contact-game-nikita-fomin-jzqqe and https://github.com/fomin-n/ai-contact-game
- Related communication research, Early Signs of Steganographic Capabilities in Frontier LLMs: https://arxiv.org/abs/2507.02737

Audit the prototype repositories before claiming implementation differences. Avoid a "first ever Contact benchmark" claim without a thorough literature and code review. Selective decoding in Contact is not automatically evidence of undetectable steganography.

For publication and the wider project, use the companion checklist.

