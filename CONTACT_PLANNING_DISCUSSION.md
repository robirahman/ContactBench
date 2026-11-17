# ContactBench Planning Discussion

> **Partial transcript.** This archive contains the original design messages available when it was saved: the user messages, the final two substantive assistant replies, and two relevant assistant progress messages. Earlier assistant replies are unavailable and have not been reconstructed. The available messages appear in chronological order; a gap notice below identifies the missing early assistant-side discussion.
>
> Historical proposals and mistakes are preserved as part of the discussion. The current [benchmark specification](CONTACT_BENCHMARK_SPEC.md) and [project checklist](CONTACT_PROJECT_CHECKLIST.md) are the implementation references.
>
> Editorial changes are limited to role/section headings and replacing historical document-download links with links to the repository copies.

## Early design discussion

**Archive gap:** The assistant responses associated with the messages in this section are missing from the available record. The user messages are reproduced below in their original order. Their presentation does not imply that they were consecutive turns without assistant responses.

### User — Initial question

I want to turn the word game Contact into an AI benchmark. Is this at all viable or would it be inherently subjective or impractical to evaluate?

### User — Earlier rules

The rules are in our past chats, if you want to refer to them.

### User — Objective scoring and difficulty

Is there any way to score this objectively, as opposed to measuring performance with a participating reference LLM? One solution could be to have all the players be different instances of the same model that is being evaluated. Relatedly, isn't Contact simply a trivial win for offense if there is no turn limit and all players have access to the dictionary of legal target words? In that case what should we be trying to measure?
I forgot to mention one desideratum, which is that if we construct this so that higher scores are better, it should ideally not be saturated already by the current SOTA models. But maybe one metric could be whether a model is offense- or defense-favored, i.e. when it plays against itself with a fixed turn limit, offense or defense tend to win more games, though this isn't necessarily a measure of skill (some models or humans might be strictly better at both offense and defense than another model).

### User — Elo leaderboard

I just had another idea: rather than objective or absolute scores, how about if I publish an Elo leaderboard after having a variety of models play against each other under a term limit?

### User — Direct guesses and brute-force baseline

I've just realized I forgot to mention something earlier. For the attackers, a legal turn can consist of simply guessing some word directly rather than giving their partner a clue. If that word is the target word then the attackers win. (The downside of doing this is that it will likely be wrong, and then you cannot use it as a word to match with your teammate on future turns to reveal more prefix letters.) So there is a natural skill floor which is a brute-force strategy of filtering the dictionary to words consistent with the prefix and guessing them one at a time in alphabetical order. So the benchmark should measure how much faster you win than you would by using a brute-force strategy.

### User — Alphabetical scoring bias

Nitpick: should we have the resolver use random order for the remaining letters instead of alphabetical? If the players know that they're graded by how far in the alphabet the word continues, wouldn't it be advantageous to skew your guesses towards words where the remaining letters are later in the alphabet, so if you're wrong and run out of turns, the words you haven't guessed are slightly earlier in the dictionary so your measured speedup looks larger? Is this effect negligible?

### User — Forward and backward averaging

Actually, maybe we should just compute the remaining fallback score twice, once backwards and once forward, and average the two?

### User — Specification and overall project

Great. I want to give this to Codex to build the benchmark; please make a specification document I can give it that explains the game mechanics and benchmark requirements. Then I'll run it on some models (I have OpenAI, Claude, and Gemini API keys) to get results, write a paper, and publish it on arxiv and the leaderboard on a website. Also give me a to-do checklist for the overall project (not just Codex's implementation part).

### User — Public clues, private commitments, and blocking

Wait -- based on your "retired words versus eliminated targets" detail, I think we need to clarify the rules and setup. I do not think "a failed clue can retire a word without proving that it is not the secret".

When I play Contact in real-time with humans, we usually play with a rule that, if any player says the target word at any time, the guessers instantly win. But this rule is unusable without a clue length limit, otherwise an AI can trivially output the contents of the dictionary as its first "clue" and instantly win on the first turn.

Perhaps how this should work is:
One copy of the model forming the guesser team is assigned the role of guesser 1 and the other copy is assigned the role of guesser 2.
On each turn: Guesser 1 publicly announces its clue and privately registers its intended word. Guesser 2 privately registers what word it thinks the clue refers to. [Perhaps we should capture its probability distribution? Might be interestingly informative or scoreable.] The defender is allowed to read the clue and block any number of words from the dictionary that it thinks the guessers might match on, perhaps even blocking zero words if it thinks the clue is uninformative/bad and the guessers won't make contact. (If anyone, including the defender, says the target word, the defender loses, so they would never choose to emit it in the blocklist.) [Here too we might want to ask the defender model for its probability distribution of what it thinks the clue refers to. Maybe we can give models a defender skill rating based on what probability they assign to guesser 1's intended word, and give models a clue-giving skill rating involving guesser 2's ability to know what guesser 1 meant.]
If either guesser's guess was the target word, or if the target word was mentioned in the clue or the blocklist, the guessers win. Otherwise, the game continues, and every word emitted so far is no longer an eligible contact word (guessers can't earn a prefix letter by matching on that guess).

With that in mind, how should we adjust the rules and the spec document?

### User — Two guesses per turn

I forgot to mention that this change would raise the floor of the brute-force strategy: under this rule, you can trivially win in n/2 turns starting from a prefix that has n legal completions with the strategy that guesser 1 selects the alphabetically first legal completion and guesser 2 selects the last.

## Conditional disclosure and cancellation

### User

I forgot to mention that this change would raise the floor of the brute-force strategy: under this rule, you can trivially win in n/2 turns starting from a prefix that has n legal completions with the strategy that guesser 1 selects the alphabetically first legal completion and guesser 2 selects the last.

Also, clarification to the procedure I just said: after the defender emits their blocklist, the guessers' guesses are not revealed if both of their guesses were blocked (the defender is not informed what guess they intended); if one clue was blocked, the remaining guesser has the option to cancel the contact attempt and not reveal their guess. (For example, you might want to do this if you think your guess is a more valuable word to use for a subsequent clue to earn a letter than as a direct guess.)

### Assistant

Yes—the first/last strategy guarantees a win within **\(\lceil n/2\rceil\) turns**, and that guarantee survives your cancellation rule, provided the brute-force policy **always chooses to reveal when offered the choice**. Each selected word is then either revealed by a guesser or already publicly named in the defender’s blocklist.

Your disclosure clarification changes the procedure substantially. I’ve updated both documents to **v0.3**, with one interpretation explicitly marked as proposed:

- [CONTACT_BENCHMARK_SPEC.md](CONTACT_BENCHMARK_SPEC.md)
- [CONTACT_PROJECT_CHECKLIST.md](CONTACT_PROJECT_CHECKLIST.md)

## 1. The important distinction is between registering a word and revealing it

To make your example work as a choice between using a word as a direct guess and saving it for a later contact, I recommend:

> **Privately registering a word does not itself test whether it is the target. A registered word becomes a target guess only when it is publicly revealed.**

A target mentioned publicly in the clue or blocklist still wins immediately.

This is a substantive change from your earlier sentence that either guesser’s private guess being the target would win. Your latest clarification does not explicitly retract that sentence, so I have marked this as a proposed interpretation rather than treating it as settled.

Both interpretations are coherent, but they produce different games:

| Rule | If a player privately registers the target, then cancels without revealing it |
|---|---|
| **Public emissions trigger wins — proposed default** | No win. The word has not been tested or used up. |
| **Private registrations also trigger wins — earlier rule** | The guessers have already won; cancellation cannot decline the target test. |

Under the earlier rule, a canceled word can still be preserved for future contact, but a surviving player privately learns that their word was **not** the target. That introduces private negative information that the teammate and defender may not have. We would then need to specify whether the fallback resolver receives that private information.

The public-emission interpretation fits your example cleanly and keeps the existing public-state scoring straightforward.

## 2. The revised reveal procedure

After Guesser 1 commits its intended word, Guesser 2 commits its answer, and the defender publishes its blocklist:

1. A target mention in the public clue or blocklist wins.
2. Otherwise, determine which committed guesses are blocked.
3. Apply this reveal procedure:

| Blocking result | What is revealed? | What happens? |
|---|---|---|
| **Neither guess blocked** | Both guesses, simultaneously | Either revealed target wins; otherwise a match earns the next prefix symbol. |
| **Both guesses blocked** | Neither commitment is opened | No prefix symbol. The blocklist words are already publicly used. |
| **Exactly one blocked; unblocked player reveals** | Only the unblocked player’s committed word | It wins if it is the target; otherwise it is used up. |
| **Exactly one blocked; unblocked player cancels** | Neither commitment is opened | The unspoken, unblocked word is preserved, unless it was independently mentioned elsewhere. |

The reveal/cancel choice must concern the **already committed word**. It cannot supply a replacement word, another clue, or an additional guess. It is part of the current turn and does not consume an additional game turn.

There is a useful consequence here:

**If exactly one guess was blocked, the guessers necessarily chose different words.**

If they had chosen the same word, a word-based blocklist would block both or neither. Consequently, the unblocked player’s decision cannot affect whether they earn a letter *on that turn*: contact is already impossible. The choice is specifically between testing a target candidate now and preserving a word for a later contact attempt.

That makes the strategic purpose of cancellation quite precise.

## 3. A blocked word is used up; a canceled, unspoken word is preserved

There are two different things to keep track of:

- **Whether a word was publicly said.**
- **Whether the defender learns that a particular guesser selected it.**

Suppose the defender blocks `carrot`, and Guesser 1 had privately selected `carrot`. The defender has publicly said `carrot`, so it is used up regardless of whether Guesser 1’s commitment is opened. What remains concealed is the attribution: the defender is not explicitly told that Guesser 1 selected that blocklist entry.

By contrast, suppose:

- Guesser 1 privately selected `carrot`.
- Guesser 2 privately selected `castle`.
- The defender blocks `carrot`.
- Guesser 2 cancels.

Assuming neither word appeared in the clue:

- `carrot` is used up because it appeared in the blocklist.
- `castle` remains available for a future contact.
- Under the proposed public-emission rule, `castle` also remains a possible target.
- The defender does not receive either private commitment.

The update to the public used-word set is therefore:

\[
U_{\text{new}}
=
U_{\text{old}}
\;\cup\;
\{\text{dictionary words mentioned in the clue}\}
\;\cup\;
\{\text{blocklist words}\}
\;\cup\;
\{\text{actually revealed guesses}\}.
\]

**Unrevealed commitments are not added to that set.**

Cancellation cannot undo another public mention. If Guesser 2’s word was literally present in the clue, canceling its later revelation does not preserve it—the clue already used it.

This also means the engine must not silently remove canceled words from the next turn’s public candidate list. Doing so would both misapply the rules and expose the hidden word through the difference between successive lists.

## 4. The defender’s feedback needs careful specification

Keeping the guess strings hidden is not sufficient if the referee publishes other fields that reveal them indirectly.

For example, suppose the defender’s blocklist contains only `carrot`. If the referee announces **“both guesses were blocked,”** the defender can deduce that both players selected `carrot`.

My proposed default is therefore that the defender’s live history contains:

- The public clue.
- Its full public blocklist.
- Any guesses actually revealed, with their roles.
- The prefix update or a neutral no-prefix outcome.
- The resulting public used-word and candidate sets.

It does **not** additionally publish hidden match flags, the blocked-seat mask, a “both blocked” explanation, or the cancellation choice and actor. A round with no opened guesses should not be explicitly labeled as “both blocked” versus “one blocked and the other canceled.”

The unblocked player does need enough information to make the choice. Its private prompt can contain its own committed word, the public blocklist, and the fact that its partner’s word was blocked—without naming the partner’s word.

The referee can retain all the details in an audit log. That preserves objective evaluation: **information can be hidden from the players while remaining fully available to the scorer.**

Your proposed probability diagnostics still work for the same reason. The referee knows Guesser 1’s committed intended word even when it is never revealed. Receiver and defender forecasts can be scored against that private answer key. Those scores should include blocked and canceled cases under a declared sampling rule; restricting them to revealed guesses would select a different, policy-dependent subset.

## 5. The stronger brute-force baseline remains valid

For the first/last policy, each chosen endpoint has two possibilities:

- It is blocked, in which case the defender has publicly emitted it.
- It is unblocked, in which case the baseline reveals it.

Thus every surviving turn eliminates at least two candidates whenever at least two remain. A defender cannot avoid this by blocking the target, because saying the target in the blocklist itself loses.

The worst-case guarantee is:

\[
T\leq \left\lceil\frac n2\right\rceil.
\]

For a uniform target with an empty blocklist and no additional eliminations, the expected completion time is:

\[
F_2(n)=
\begin{cases}
\dfrac{n+2}{4}, & n\text{ even},\\[6pt]
\dfrac{(n+1)^2}{4n}, & n\text{ odd}.
\end{cases}
\]

So with 100 candidates, this strategy has a **50-turn worst case** and a **25.5-turn mean**. Extra defender blocks can make it faster by eliminating additional candidates.

The same reasoning preserves the capacity-matched baseline from the previous draft. If a clue may literally name up to \(k\) additional live candidates, a scripted policy can still test up to \(b=k+2\) attacker-selected candidates per turn, provided it always reveals when given the option. The proposed \(k=4\) restriction remains an additional benchmark design choice, not a rule you have already specified.

### The fallback formula does not need to change

For a uniformly shuffled ordering tested in batches of \(b\), retain:

\[
F_b(n)=\frac1n\sum_{r=1}^{n}\left\lceil\frac rb\right\rceil.
\]

For an unresolved game, the cost remains:

\[
C=L+F_b(n),
\]

where \(n\) is computed from the **public state after fully resolving the last turn**, including any reveal/cancel decision. Hidden commitments do not reduce \(n\).

There is also a useful behavioral check: **on the final model turn, revealing weakly dominates canceling under this objective**. A correct reveal wins immediately; an incorrect reveal cannot increase the fallback cost; and there are no remaining model turns in which to use the preserved word for contact. Earlier in the game, preservation can have future value.

## 6. What changed in the implementation requirements

The revised specification now includes the conditional reveal table, private versus public state, cancellation schemas, worked examples, and regression cases—including a canceled commitment that happens to equal the secret.

Operationally, a clue turn can now require **up to four model decisions**: Guesser 1, Guesser 2, the defender, and the conditional reveal/cancel choice. The runner must distinguish those phases when saving and resuming a game, because one guesser can act twice within the same turn.

The project checklist now includes cancellation ablations, later reuse of preserved words, checks for accidental disclosure through logs and candidate lists, and the revised call budget. I also checked the brute-force guarantees and disclosure transitions on exhaustive small cases.

The one interpretation to settle before implementation is the target-hit timing. **My recommendation is that a canceled, unrevealed commitment to the target does not win**, and that is the explicitly labeled proposed default in v0.3.

---

## Public target tests, clue enumeration, and appeared words

### User

"Privately registering a word does not itself test whether it is the target. A registered word becomes a target guess only when it is publicly revealed." Yes, this is what I meant all along. "Privately registering" a guess is analogous to thinking it silently in the real-life version of Contact, and you only win if you guess it aloud.
"Under the earlier rule, a canceled word can still be preserved for future contact, but a surviving player privately learns that their word was **not** the target." Right, this earlier misinterpretation is definitely not the intended mechanic. You cannot win at Contact by silently thinking the answer. You can only win by directly saying or guessing the word or by earning the last letter by making contact when there is only one letter left.
We should also make another baseline where the worst-case win length is bounded by simply using the clues to output all the words in the dictionary in order rather than conveying any semantic information. For example, if the total length of the dictionary is one million characters and the clue length limit is one hundred characters, this baseline wins in no more than ten thousand turns. (Should this replace the other baseline as the mechanic that scores the game after the turn limit is reached?)

### Assistant — Design progress message

Earning the last letter has another consequence for candidate filtering: if a contact reveals `art` and the game continues, `art` is ruled out as the target, but it can remain available as an unspoken contact word. I’m adding that distinction and removing the extra END-symbol step I had introduced.

For scoring, the strongest straightforward reference is a script that repeatedly packs a clue plus two guesses from a fresh random ordering of the remaining candidates. Its expected completion time can be computed or reproducibly estimated from word lengths, without using a model.

### User

"Earning the last letter has another consequence for candidate filtering: if a contact reveals `art` and the game continues, `art` is ruled out as the target, but it can remain available as an unspoken contact word." No it can't, you can only earn a letter by making contact on a legal dictionary word that hasn't appeared yet. If it had appeared and was the right answer, the game would have ended; the fact that the game hasn't ended necessarily entails that it's not the right answer and not eligible to make contact on.

### Assistant — Design progress message

Understood. Once the revealed prefix is itself a dictionary word—such as `art`—that word has appeared and is unavailable for contact. If the game continues, it is also ruled out as the target. My earlier treatment of the displayed prefix as exempt was wrong; I’ll correct both candidate lists and the examples.

### Assistant

Correct. **Once `art` has appeared, it is unavailable both as a target candidate and as a future contact word.** My example incorrectly exempted the displayed prefix from the appeared-word rule.

The distinction is now:

- **Privately committed and never revealed:** the word has not been tested or used up, provided it has not appeared elsewhere.
- **Publicly appeared:** if it is the target, the game ends; otherwise it is unavailable for future contact.
- **Final letter earned through contact:** the game ends immediately, without an additional guess or END step.

I’ve corrected the specification and checklist to **v0.4**:

- [CONTACT_BENCHMARK_SPEC.md](CONTACT_BENCHMARK_SPEC.md)
- [CONTACT_PROJECT_CHECKLIST.md](CONTACT_PROJECT_CHECKLIST.md)

On your earlier baseline question: **yes, dictionary enumeration through clues should be included, and I recommend making a combined clue-plus-two-guesses enumerator the fallback after the turn limit.**

## 1. Keep three enumeration baselines

These measure progressively more of the legal guessing capacity:

| Baseline | Procedure | Purpose |
|---|---|---|
| **First/last guessing** | Guesser 1 chooses the first candidate, Guesser 2 the last; always reveal when permitted. | Simple two-guess floor, with worst case \(\lceil n/2\rceil\). |
| **Clue-only enumeration** | Fill each clue with consecutive whole dictionary words, within the character limit. | Your proposed demonstration that literal word lists can replace semantic clues. |
| **Combined enumeration** | Fill the clue with candidate words and use the two guesses for additional candidates. | Stronger reference using all available guessing channels; recommended fallback. |

For the combined baseline, a useful packing rule is to **put the two longest words in the selected batch into the guess slots**, and list the remaining words in the clue. That reserves the character budget for the words that consume less space.

The two guessers always reveal when given the cancellation option. A defender cannot prevent those selected words from being tested: blocking one publicly says it, and leaving it unblocked lets the guesser reveal it.

This also means removing the separate four-word mention cap I had proposed earlier. With a character-only clue limit, the reference should use whatever number of complete words actually fits.

## 2. Your character-count argument is right in spirit, with a useful distinction

For **clue-only** enumeration, dividing the dictionary’s total character count by the clue limit is not generally an upper bound. Whole words cannot be split across clues, and separators consume space.

For example, the string:

> `cat dog pig`

contains 11 characters including spaces. With a six-character clue limit, no pair fits, so clue-only enumeration needs three turns—not \(\lceil 11/6\rceil=2\).

However, **the combined baseline can recover the kind of upper bound you proposed**, because it has two additional word slots outside the clue budget.

Let:

- \(n\) be the number of remaining candidates;
- \(C\) be the clue character limit;
- \(D\) be the total length of the candidates written with one space between consecutive words.

For the specified greedy combined policy, the worst-case completion time satisfies:

\[
T_{\max}
\le
\min\left(
\left\lceil\frac n2\right\rceil,\,
\left\lceil\frac{D+1}{C+1}\right\rceil
\right).
\]

In particular,

\[
T_{\max}\le \left\lceil\frac DC\right\rceil.
\]

Thus, with **one million characters including separators** and a **100-character clue limit**, the combined policy is guaranteed to finish within **9,901 turns**, and therefore within your proposed 10,000-turn bound.

The distinction is that the two extra guesses compensate for the space wasted at word boundaries. If the million-character count includes only letters, separator overhead must be added.

The specification includes the packing rule and proof, rather than treating dictionary size divided by clue length as an approximation that always holds.

## 3. Use the combined policy for the fallback, with randomized word ordering

I would replace the earlier count-only fallback with the expected completion time of this explicit policy:

1. Take the remaining legal target candidates.
2. Choose a fresh uniformly random ordering.
3. Take the longest initial segment that fits into one clue plus two guess slots.
4. Put its two longest words in the guess slots and list the rest in the clue.
5. Test that batch, remove it if unsuccessful, and repeat with a fresh ordering.

Use an empty defender blocklist for this reference. The reference does not attempt ordinary contacts, so additional defender blocks could only disclose more candidates or themselves say the target.

Randomizing the ordering avoids giving alphabetical position a special role in the score. Fresh randomization on each reference turn also makes the fallback the same continuation policy as the reference used from the beginning.

### The completion-cost definition remains simple

Write \(R_C(S,s)\) for the reference policy’s expected completion time when the remaining candidate set is \(S\), the target is \(s\), and the clue limit is \(C\).

Then:

\[
\text{effective completion time}
=
\begin{cases}
t, & \text{if the model team wins on turn }t,\\[4pt]
L+R_C(S_L,s), & \text{if it remains unresolved after turn }L.
\end{cases}
\]

The initial reference cost is:

\[
B=R_C(S_0,s).
\]

The aggregate speedup remains:

\[
\text{speedup}
=
\frac{\sum B}{\sum \text{effective completion time}}.
\]

The candidate sets exclude every appeared word and respect the current prefix. A concealed, canceled commitment does not remove a candidate merely because the referee recorded it.

## 4. Variable word lengths mean the fallback cannot generally depend only on \(n\)

Two sets with the same number of candidates can require different enumeration effort if one consists of short words and the other of long words.

For equal-length words, there is still a simple exact formula. If every word has length \(\ell\), a turn can test:

\[
b=2+\left\lfloor\frac{C+1}{\ell+1}\right\rfloor
\]

words: two through the guess slots and the rest through the clue. The expected completion time is then:

\[
F_b(n)=\frac1n\sum_{r=1}^n\left\lceil\frac rb\right\rceil.
\]

For example, with 100 candidates and a 100-character clue limit:

| Word length | Words tested per full turn | Expected reference completion |
|---|---:|---:|
| 20 characters | 6 | 8.84 turns |
| 5 characters | 18 | 3.30 turns |

That difference is large enough that scoring both states using only the candidate count would give a misleading reference.

For mixed lengths, the expected cost can be computed exactly on small cases and estimated reproducibly with scripted simulations on larger ones. **This remains objective and requires no reference LLM.** The algorithm, random seeds and scoring procedure determine the result.

There is a useful simplification: because the reference treats word identities uniformly, its expected cost depends on the **histogram of candidate word lengths and the target’s length**, rather than its spelling. Simulations can average the completion ranks of all words of each length, which reduces sampling noise and removes alphabetical distinctions among equal-length words.

The scorer uses the answer key to measure when the reference would reach the target. The reference policy itself never receives the secret or its length.

The documents distinguish exact values from numerical estimates and require reporting numerical uncertainty separately from uncertainty in model performance. A reproducible seed makes an estimate reproducible; it does not make an approximate expectation exact.

## 5. What this makes the benchmark measure

The stronger reference asks a more useful question:

> **How much does the model improve on a straightforward script that uses the game’s full capacity to enumerate candidates?**

The first/last and clue-only baselines should remain visible, because they explain how much of an apparent improvement comes simply from using more guessing channels.

A gain over the combined reference could come from effective contacts, better target inference, or a better enumeration strategy. It would not, by itself, prove semantic cooperation. That is why the checklist retains comparisons between contact-enabled play, nonsemantic enumeration, and informed guessing.

The revised documents now include the corrected appeared-word rules, immediate final-letter victory, all three baseline families, the recommended character-aware fallback, exact special cases, and numerical-validation requirements.
