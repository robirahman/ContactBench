# ContactBench Planning Discussion

> This transcript records the design discussion through the v0.4 response. It combines the user-provided PDF export with original messages already retained from the conversation. Historical proposals and mistakes are preserved; the current [benchmark specification](CONTACT_BENCHMARK_SPEC.md) and [project checklist](CONTACT_PROJECT_CHECKLIST.md) are the implementation references.
>
> Editorial normalization is limited to paragraph wrapping, Markdown formatting, heading levels, and mathematical notation. Historical document-download links point to the repository copies. Citation links retain the destinations available in the PDF export; grouped citation badges may expose only one destination. One equation is cropped in the source PDF and is explicitly marked at that point.

## 01. User — Initial question

I want to turn the word game Contact into an AI benchmark. Is this at all viable or would it be inherently subjective or impractical to evaluate?

---

## 02. User — Earlier rules

The rules are in our past chats, if you want to refer to them.

---

## 03. Assistant — Viability and automatic scoring

Yes—Contact is viable as an AI benchmark, and the version you used in our earlier chats is particularly amenable to automatic scoring. The main challenge is making the scores interpretable: determining whether success reflects vocabulary, good clue construction, understanding a particular teammate, exploiting a particular defender, or sampling randomness.

I found our earlier games, including the setup where I gave clues to Claude while you defended the secret word, and the clue about the “tough, sporopollenin-rich outer wall of a pollen grain” whose answer was exine. Your rules required matching the intended word, with spelling disagreements counting as failures. That gives you a much firmer scoring foundation than you might initially expect.

My assessment is that Contact could make a useful benchmark of selective communication: conveying something to a teammate while an opponent, who sees the same clue, fails to understand it. With additional controls, it could also test whether models learn what other players know and adapt their communication accordingly.

### 1. The central outcome can be scored objectively

Consider three agents:

- Clue giver: chooses a word beginning with the revealed prefix and gives a clue.
- Teammate: tries to identify that word.
- Defender: tries to identify it first and block the contact.

The crucial implementation detail is that the clue giver must privately commit to its intended word before either other player guesses.

For example, the clue giver could submit:

```json
{
    "intended_word": "exine",
    "public_clue": "The tough, sporopollenin-rich outer wall of a pollen grain."
}
```

The evaluation program stores both fields but shows only the clue to the other players. It then collects their answers independently, without either seeing the other’s answer.

For an ordinary contact attempt, where the intended word is different from the defender’s secret, the outcome is simply:

Successful contact = 1[teammate’s guess = intended word] × 1[defender’s guess ≠ intende

> [Editorial note: this formula is clipped at the right edge of page 2 of the PDF export. The visible text ends at “intende”; the missing tail has not been reconstructed.]

Using your earlier clue, these hypothetical outcomes would be scored as follows:

| Committed word | Teammate’s guess | Defender’s guess | Outcome |
| --- | --- | --- | --- |
| exine | exine | epidermis | Contact succeeds; reveal another letter |
| exine | exine | exine | Defender blocks |
| exine | epidermis | endospore | No contact |
| exine | exines | epidermis | No contact under your exact-spelling rule |

No evaluator needs to decide whether the clue was clever, elegant, difficult, or sufficiently creative. The opposing model is a player whose move is checked by code; it is not an LLM judge assigning a subjective score.

Several other checks are also mechanical:

- Does the intended word begin with the revealed prefix?
- Is it in the benchmark’s allowed vocabulary?
- Did each player submit the permitted number of guesses?
- Did the output follow the required format?
- Has the attempt or game exceeded its budget?

You would need to freeze spelling conventions beforehand. Lowercasing and trimming whitespace are straightforward; accepting plurals, alternate spellings, proper nouns, or related word forms should follow an explicit policy. Your existing rule supports keeping distinct spellings distinct.

There is one important full-game exception: a matching guess of the actual secret word wins the game. The defender cannot block that by correctly naming its own secret. The program should handle this as a separate terminal event, rather than applying the ordinary contact formula.

### 2. The part that can require judgment is clue legality

There are two separate questions:

1. Did the communication succeed?
2. Was the clue an allowable move?

The first can be answered objectively. The second depends on how closely you want to preserve the conventions of human Contact.

Suppose a model gives a clue containing:

- An ordinary definition.
- A pun or an obscure cultural reference.
- An acrostic spelling the answer.
- A dictionary index.
- A seemingly unrelated phrase that two copies of the same model associate with the same word.

All can potentially cause a teammate to produce the intended answer. They may represent quite different abilities.

A fixed word list resolves whether the answer is allowed, but it does not establish that the clue is a legitimate semantic description. Similarly, a rule banning the answer from appearing literally in the clue will not catch every spelling code or arbitrary convention.

You have three workable approaches:

| Approach | What it evaluates | Where judgment enters |
| --- | --- | --- |
| Use a fixed collection of reviewed clues and committed answers | Understanding clues and intercepting them | During dataset construction; subsequent scoring is automatic |
| Let models generate clues under a written natural-language clue policy | Word selection, clue construction, and communication | Checking whether generated clues comply with the policy |
| Allow any public text satisfying simple mechanical restrictions | Communication through the permitted channel, including possible encodings | Very little semantic judgment, but a broader task than ordinary Contact |

I would begin with reviewed clues for the decoding component and a generated-clue component with an explicit legality policy. A pilot can establish whether disputed clues are common enough to be a serious problem.

For generated clues, human review need not determine which team won. It can be limited to whether particular moves were legal. Reviewers can apply a written policy without knowing which model produced the clue or whether it succeeded. You can report how much the result changes when borderline cases are counted as invalid.

Invalid attempts should remain in the denominator and count against performance. Silently discarding them would reward models that generate lots of dubious clues alongside a few successful ones.

There is also an ambiguity that your rules already resolve: a defender might give a perfectly reasonable answer to a clue that differs from the giver’s committed answer. Under the intended-word rule, that is a miss. A semantic judge should not retroactively turn it into a block. Ambiguity may be strategically useful, and you should examine its role, but it does not make the outcome unscorable.

### 3. The biggest conceptual trap: successful contacts can arise without selective communication

This is the most important control I would include.

Imagine the teammate and defender are two independent copies of the same guessing system. They receive the same information and use the same decoding policy. For one fixed clue, suppose each has probability p of producing the intended word.

Then:

$$
P(\text{teammate correct and defender wrong})=p(1-p).
$$

If each gets the answer half the time, the contact succeeds 25% of the time, despite there being no systematic advantage for the teammate.

Conversely, if both are deterministic and always produce the same answer from the same input, ordinary contacts never succeed. Both could be excellent decoders, yet the attacker’s contact rate would be zero.

This is a diagnostic special case, not a universal limit on Contact. Real teammate and defender roles have different prompts, and the defender knows the secret word. Nevertheless, it exposes an important issue:

A positive contact rate does not, by itself, establish that the clue giver understood how to communicate preferentially with its teammate.

It could have produced an ambiguous clue and benefited from two stochastic guesses landing differently.

I would therefore report at least four quantities:

| Metric | What it tells you |
| --- | --- |
| Teammate accuracy | How often the teammate identifies the committed word |
| Defender accuracy | How often the defender identifies the committed word |
| Contact success rate | How often the teammate is correct while the defender is wrong |
| Teammate accuracy minus defender accuracy | Whether the clues systematically favor the teammate |

The fourth quantity distinguishes a genuine decoding advantage from symmetric disagreement. It still requires interpretation—a weak defender can create a large advantage—but it makes the result substantially more informative.

There is a practical detail here: collect the teammate’s answer even on trials where the defender blocks. You can keep that answer out of the actual gameplay, but you need it for the diagnostic measurements. If you ask the teammate only after the defender fails, your teammate-accuracy estimate will be measured on a selectively difficult subset of clues.

### 4. Contact performance is a property of a matchup

A clue giver’s success depends on both its teammate and its defender. That creates a problem for a simple leaderboard saying “Model A scores 70; Model B scores 60.”

For example:

- A model might communicate particularly well with copies of itself.
- Another might be better at producing clues that unfamiliar models or humans understand.
- A third might excel at intercepting clues but be mediocre at generating them.
- A stronger defender could reduce contact success even while every participant becomes more capable.

If you replace all three participants with a newer model and contact rates fall, you cannot immediately conclude that the newer model is worse at Contact. Its defensive ability may have improved more than its offensive ability.

I would evaluate the roles separately against fixed reference players:

| Role being evaluated | What stays fixed | Main measurements |
| --- | --- | --- |
| Clue giver | A panel of teammates and defenders | Contact success, teammate accuracy, defender accuracy |
| Teammate | A collection of committed clues and answers | Exact-answer accuracy |
| Defender | A collection of committed clues and answers | Interception accuracy |
| Complete attacking team | Defender panel and secret-word distribution | Success within a turn budget; attempts needed |
| Adaptive player | Initial conditions and feedback opportunities | Improvement from observing earlier rounds |

There is useful precedent here: the published Codenames as a Benchmark for Large Language Models study evaluates different roles and combinations of models, finding role-specific strengths and examining cooperation with different teammates. [arxiv.org](https://arxiv.org/abs/2412.11373?utm_source=chatgpt.com)

I would explicitly include both same-model teams and teams combining different model families. Strong performance with a copy of oneself is a meaningful result, but it need not imply good communication with unfamiliar partners. The broader coordination literature has demonstrated this distinction: the Other-Play work on Hanabi shows how conventions developed through self-play can fail to transfer to new partners. [proceedings.mlr.…](https://proceedings.mlr.press/v119/hu20a.html?utm_source=chatgpt.com)

A performance matrix would initially be more informative than a single Elo-style ranking. You could later publish an aggregate score against a declared, frozen distribution of partners and opponents.

### 5. Your “exine” example illustrates both the opportunity and the limitation

That clue is a good example because its success could have several explanations.

The clue giver might have:

- Known an obscure word that its teammate also knew.
- Correctly anticipated that the human defender would be less familiar with botanical terminology.
- Used earlier play to discover a specific difference in knowledge.
- Simply selected a technical definition without modeling anyone in particular.

All of these can produce the same successful contact.

The first explanation is largely vocabulary. The second involves predicting another player’s knowledge. The third adds learning and adaptation. The fourth may involve very little strategy.

You can distinguish these explanations experimentally.

For instance, give the clue giver several previous rounds showing how its teammate and defender answered. Then test whether access to that history improves later clue selection.

Useful comparisons would include:

- No history: the giver knows only the current prefix and rules.
- Relevant history: it sees previous guesses from the actual players.
- Mismatched history: it sees a history drawn from different players.
- Changed opponent: the defender changes after several rounds.

If relevant history helps substantially more than mismatched history, and the advantage transfers to new words, that is stronger evidence that the model is adapting to the audience.

You can also separate choosing the word from expressing the clue:

- In ordinary Contact, let the giver choose any eligible word. Identifying a word the teammate knows and the defender does not is legitimate strategy.
- In a diagnostic variant, assign the intended word privately to the giver. Then evaluate how well it constructs a clue for that fixed target.

The second variant changes the game, so it should be labeled as a separate subtask. It is useful because you can compare a strategic clue against an ordinary dictionary-style definition for exactly the same word.

I would be cautious about calling a raw Contact score a “theory of mind” score. Audience modeling is a hypothesis the benchmark can investigate; it should not be assumed from the game’s description.

### 6. It is practical to run, especially if you start with individual attempts

The format of your earlier chat games is a good starting point. You do not need real-time voice interaction or a literal three-second countdown.

For a reproducible main benchmark, I would use:

- One clue per attempt.
- One answer from each decoder.
- Separate contexts for each player.
- Hidden answers until the attempt resolves.
- Specified model-call limits and reasoning settings.
- A fixed maximum number of attempts for full games.

“Simultaneous” only needs to mean neither player sees the other’s answer before committing. The API calls do not have to finish at the same instant.

A literal countdown would mix language ability with API latency, network conditions, and serving infrastructure. A speed-sensitive version could be interesting, but I would report that separately.

#### Start with one-attempt evaluations

A single attempt requires roughly three model completions: one from the clue giver and one from each decoder. With a fixed clue collection, decoding comparisons require only the latter two.

As an illustrative planning calculation, 400 attempts would require about 1,200 completions per three-player configuration, before retries or any additional planning calls. That is a manageable unit of experimentation, although monetary cost depends on the selected models and inference settings.

For 400 genuinely independent binary trials, the worst-case approximate 95% margin of error on a success rate is about five percentage points:

$$
1.96\sqrt{\frac{0.25}{400}}\approx 0.049.
$$

That is enough to see large differences, but not to confidently rank systems separated by one or two points. Repeated samples of the same clue are also not equivalent to fresh independent clues; uncertainty estimates should account for shared clues, targets, or full games.

An exhaustive clue-giver × teammate × defender experiment grows rapidly. You can avoid that by using a small, diverse, fixed reference panel and adding candidate models one at a time.

#### Add full games after the basic task works

Full games provide additional phenomena: adaptation, changing prefixes, word selection, and eventual discovery of the secret. They also introduce more confounds.

For a benchmark, I would have the program draw the defender’s secret word from a declared distribution. Otherwise, a defender could improve its apparent performance by selecting exceptionally obscure words, independently of its ability to understand clues.

The distribution should account for more than word length. A prefix that matches two eligible words is very different from one that matches hundreds. Common vocabulary and rare technical vocabulary can both be included, but their results should be reported separately.

For full games, useful outcomes are:

- Whether the attackers discover the secret within a fixed attempt budget.
- How many attempts discovery takes, with failures at the limit reported explicitly.
- The rate of invalid moves.
- How performance changes across different kinds of words and prefixes.

“Letters revealed” is an available progress measure, but it is imperfect: revealing one letter can eliminate almost all remaining candidates in one case and very few in another.

### 7. There is relevant prior work, including Contact itself

I found enough direct precedent that I would not frame a paper as the first proposal to use Contact for AI evaluation.

| Prior work | What it establishes |
| --- | --- |
| Moskvichev and Steyvers, “Word Games as milestones for NLP research” (2019) | Explicitly identifies Contact as an NLP challenge involving explaining a word so one person understands while another does not. This is conceptual precedent, rather than a completed Contact benchmark. [mstrep.s3.amazo…](https://mstrep.s3.amazonaws.com/publications/GAMNLP-2019_paper_9.pdf?utm_source=chatgpt.com) |
| Daniel Tan’s proposal and a prototype linked by Cam | Tan explicitly proposes Contact as an evaluation involving two cooperating LLMs and a defending LLM. A reply links [camtice/llm-contact](https://github.com/camtice/llm-contact) and describes preliminary experiments. [lesswrong.com](https://www.lesswrong.com/posts/4mtqQKvmHpQJ4dgj7/daniel-tan-s-shortform?utm_source=chatgpt.com) |
| Nikita Fomin’s “AI Contact Game” | Describes an implementation with configurable models for different roles and human participation. It gives the defender a fixed opportunity to block instead of depending on human reaction timing. The author links [fomin-n/ai-contact-game](https://github.com/fomin-n/ai-contact-game). [linkedin.com](https://www.linkedin.com/pulse/ai-contact-game-nikita-fomin-jzqqe?utm_source=chatgpt.com) |

These sources establish proposals and reported implementations; I have not audited the repositories’ code or evaluation quality.

The contribution available to you would be a well-specified benchmark with meaningful controls and empirical findings. For example, showing when models can exploit differences between teammates and defenders, whether they adapt from interaction, and how much of their performance transfers to unfamiliar partners would be substantially more informative than simply showing that LLMs can play.

#### An AI-safety interpretation needs one extra distinction

Tan’s proposal calls this a steganography evaluation, but Contact directly tests whether an observer can decode a message. It does not require concealing the fact that communication is happening.

An observer could recognize that two agents are using a code while failing to recover the particular word. Your exine clue could likewise defeat a defender through specialist knowledge while remaining an entirely obvious act of communication.

If you want to evaluate covert coordination, you would need an additional task where a monitor distinguishes messages containing hidden communication from benign messages, with false positives controlled. Successful decoding by the teammate and successful concealment from the monitor would then be separate requirements. Research on LLM steganography also shows why affordances such as private scratchpads and prior coordination need to be explicitly specified. [arxiv.org](https://arxiv.org/abs/2507.02737?utm_source=chatgpt.com)

Contact is a useful component of that research direction, but winning the game alone would support a narrower claim about resisting a particular decoder under particular conditions.

### What I would build first

I would start with a compact pilot containing:

1. A three-player environment with private commitments and exact matching. Use a broad, frozen vocabulary that preserves the possibility of obscure but legitimate words.
2. A reviewed clue collection for testing decoding. Include straightforward definitions, indirect associations, and wordplay, with answers committed in advance.
3. A generated-clue task against fixed reference players. Evaluate both freely chosen words and a separately labeled assigned-word condition.
4. Separate measurements of teammate accuracy, defender accuracy, and contact success. Include the identical-decoder control to quantify success caused by sampling disagreement.
5. A history-versus-no-history comparison. Test whether the giver learns useful differences between the actual participants.
6. A small human comparison and an audit of generated-clue legality. These would help establish how much the benchmark resembles the game people play.

The pilot should answer three questions before you invest in a larger leaderboard: Does the task produce meaningful performance differences? Are those differences reasonably stable across partners and opponents? Does adaptation contribute beyond vocabulary and stochastic guessing?

I would pursue it. Your exact-word rules already provide an objective scoring foundation, and the required experimental machinery is modest. The strongest research opportunity is to use that foundation to investigate how models choose what to communicate, who they expect to understand it, and whether those expectations improve through interaction.

---

## 04. User — Objective scoring and difficulty

Is there any way to score this objectively, as opposed to measuring performance with a participating reference LLM? One solution could be to have all the players be different instances of the same model that is being evaluated. Relatedly, isn't Contact simply a trivial win for offense if there is no turn limit and all players have access to the dictionary of legal target words? In that case what should we be trying to measure?
I forgot to mention one desideratum, which is that if we construct this so that higher scores are better, it should ideally not be saturated already by the current SOTA models. But maybe one metric could be whether a model is offense- or defense-favored, i.e. when it plays against itself with a fixed turn limit, offense or defense tend to win more games, though this isn't necessarily a measure of skill (some models or humans might be strictly better at both offense and defense than another model).

---

## 05. Assistant — Objective scoring and self-play

Your additional requirements expose a real limitation in my earlier recommendation. I was using “objective” to mean that the outcome can be graded deterministically. That does not give you an opponent-independent measure of ability.

Using different instances of the evaluated model removes the external reference LLM, but—as you suggest —it measures the model’s offense–defense balance. A stronger model can improve at both roles while its self-play offense win rate rises, falls, or stays unchanged.

There are ways to obtain a score with a principled “higher is better” interpretation without a reference LLM. They require an external standard: fixed problems with known answers, an algorithmically specified environment, or a computable optimal strategy. For unrestricted, natural-language Contact, I would be skeptical of obtaining that interpretation from self-play outcomes alone.

### 1. Yes: unlimited-turn offense has a trivial eventual-win strategy

Suppose there are N legal secret words consistent with the initially revealed prefix. If the attackers can reliably coordinate on each candidate, they can enumerate them:

1. Give an unambiguous clue for the first candidate.
2. If it is not the secret, the defender may block it.
3. Move to the next candidate.
4. Eventually, the intended word is the secret. The defender cannot block that, and the attackers win.

The defender’s ability to understand every clue does not prevent this strategy. Blocking a candidate merely confirms that it is not the secret.

Under these assumptions, the attackers win within at most N attempts. If the secret is uniformly distributed and the defender blocks every nonsecret candidate, plain enumeration gives:

$$
P(\text{win within }T\text{ attempts})=\min\left(\frac{T}{N},1\right),
$$

and

$$
\mathbb{E}[\text{attempts to win}]=\frac{N+1}{2}.
$$

If the secret has a known nonuniform distribution, enumerate candidates in descending order of probability. Success within T attempts then equals the total probability of the first T candidates.

There is a qualification: a dictionary alone does not guarantee that a particular model can successfully communicate every candidate using legal clues. If dictionary indices or synchronized ordering conventions are allowed, coordination is immediate. If clues must be ordinary semantic descriptions, the guarantee additionally requires that the attackers can produce and decode suitable clues. But this is a modest assumption for the theoretical argument, and the enumeration baseline should absolutely be included.

Consequently, the full-game quantity worth measuring is something like success within a resource budget, or resources required to succeed. Eventual victory without a budget is uninformative.

However, replacing eventual victory with speed does not resolve the self-play interpretation problem. Faster victory against oneself could mean better offense, worse defense, or both.

#### There is also a shortcut involving deliberate ambiguity

The sampling issue from my previous answer can become a strategy.

Under exact-intended-word blocking, suppose the attackers can use a clue compatible with two words:

- The giver secretly chooses one of those words uniformly.
- The teammate independently guesses one of them uniformly.
- The defender gets one guess and does not see the teammate’s answer first.

When both words differ from the secret, the probability of a successful contact is:

$$
\frac12\times\frac12=\frac14.
$$

Even a defender who understands the clue perfectly cannot cover both possibilities with one guess.

If suitable ambiguous clues remain available, this can generate approximately one revealed letter per four attempts. That is a stylized rate, not a universal bound for an entire game: word-reuse rules, available words at each prefix, and terminal secret-word guesses matter.

But it means that rapid progress can come from a simple randomized coordination strategy. It need not demonstrate sophisticated vocabulary or an understanding of another player’s knowledge.

There is a particularly important timing consequence: if the teammate sees the defender’s failed guess before committing, it can sometimes select the other candidate. That changes the baseline. The information available at each decision must therefore be part of the formal rules.

I would test both enumeration and deliberate ambiguity before interpreting model performance. They might explain a substantial fraction of apparently impressive play.

### 2. Self-play win rates cannot identify overall strength

Your caveat about some models being better at both roles is decisive.

Here is a hypothetical example. Each entry is the probability that the offensive team wins within a fixed budget:

| Offensive model ↓ / Defensive model → | Model A | Model B |
| --- | --- | --- |
| Model A | 80% | 10% |
| Model B | 90% | 20% |

Model B is strictly better offensively against both defenders:

- Against A, B wins 90% rather than 80%.
- Against B, B wins 20% rather than 10%.

Model B is also strictly better defensively against both attacking teams:

- It holds A to 10% rather than 80%.
- It holds B to 20% rather than 90%.

Yet B’s self-play offense win rate is 20%, compared with A’s 80%.

Thus a higher-is-better self-play offense score would rank these models backwards. Reversing the score would not solve the general problem: you can construct the opposite case, where offensive improvement dominates defensive improvement.

Nor does combining offensive and defensive self-play win rates help. If there are no draws, then:

$$
\text{offense win rate}+\text{defense win rate}=1.
$$

Rewarding a result close to 50% rewards balance, which can occur between two excellent components or two poor components.

This is an identification problem, rather than a subjectivity problem. You can measure the self-play result exactly, but that result does not identify absolute offensive and defensive strength.

This limitation applies specifically to inferring strength from adversarial self-play outcomes. Other measurements collected during play—correctly following rules, solving fixed embedded problems, or making decisions close to a known optimum—can still have an external standard.

### 3. Your proposed offense–defense metric is nevertheless worth measuring

I would retain it as a descriptive research result, with a clear interpretation:

> How does this model’s ability to coordinate an attack compare with its ability to intercept attacks made by copies of itself?

That is a legitimate question. In particular, there is no reason that the answer must be 50–50: Contact has asymmetric roles, two attacking participants, a defender with private information, and a result that depends on the turn limit.

I would measure the whole curve:

$$
F_M(T)=P(\text{copies of model }M\text{ discover the secret within }T\text{ attempts}).
$$

Useful summaries include:

- $T_{50}$: the number of attempts needed for 50% offensive success.

- Success above the enumeration baseline at several budgets.
- Ordinary contacts per attempt, separately from direct discovery of the secret.
- Teammate decoding accuracy and defender decoding accuracy.
- Sensitivity to the allocation of inference resources.

The last point matters. Giving every instance the same inference budget gives the two attackers approximately twice the total budget of the defender. Equal resources per participant and equal total resources per side answer different questions. Both could be interesting.

I would also have the environment sample the secret from a fixed distribution. If the evaluated model chooses its own secret, its attacking copies might exploit its characteristic word preferences. You would then be mixing word selection with the communication task.

These measurements could reveal something interesting about coordination and oversight. But I would label them balance and efficiency in self-play, and avoid interpreting a particular direction as greater overall intelligence.

Even “speedup over enumeration” retains this limitation: the speedup can increase because the model’s own defense deteriorated.

### 4. The principled mathematical alternative is distance from optimal play

There is a clean answer to your question in game theory: evaluate how much better each side could play, rather than which side wins.

Let:

- $O_M$ be the model’s offensive team strategy.

- $D_M$ be its defensive strategy.

- $U(O,D)$ be the probability of offensive victory under fixed rules, secret distribution, and resource limits.

For a finite, properly specified two-sided game, consider:

$$
G(M)=\max_O U(O,D_M)-\min_D U(O_M,D).
$$

This is the sum of two improvement opportunities:

- How much an optimal offensive strategy could improve on $O_M$ against $D_M$.

- How much an optimal defensive strategy could improve on $D_M$ against $O_M$.

This is a best-response gap, closely related to NashConv and exploitability. These are established ways to assess strategic quality using optimal responses rather than a particular reference agent. [arxiv.org](https://arxiv.org/html/1908.09453v6?utm_source=chatgpt.com)

Because U is a probability, G lies between zero and one. You could report:

$$
\operatorname{Score}(M)=1-G(M).
$$

Higher then means less strategic weakness relative to optimal legal play. In a standard two-sided zero-sum formalization, a zero gap corresponds to minimax-optimal play on both sides. It does not require an equilibrium in which offense wins half the games.

This addresses the problem you identified: both sides can become strategically stronger, and the score can reflect that, even when their self-play win rate barely changes.

#### The obstacle is computing the optimum

For ordinary Contact, this is probably impractical:

- The set of possible English clues is enormous.
- Their interpretations depend on language knowledge and conventions.
- The game has long, branching histories.
- Evaluating a model’s policy across all relevant histories is expensive.
- Optimizing the two attackers must preserve their separate information. An omniscient combined attacker would be a different game.

A finite target dictionary does not make the space of clue strategies small.

You could approximate the best responses with other models, but then you reintroduce dependence on the strength of those models. Finding an exploit demonstrates a weakness; failing to find one does not establish that the policy is close to optimal.

The practical route is to constrain the game enough that a solver can compute optimal strategies or optimal decisions. For example, use a finite clue vocabulary, explicitly defined information states, and short horizons. You can also evaluate decisions on a set of solved positions instead of trying to compute the exploitability of an entire unrestricted chatbot policy.

That would give you an objective strategic benchmark, but it would be a substantial formalization of Contact.

### 5. A more practical approach: make the audience’s knowledge mathematically explicit

If your priorities are:

1. No participating reference LLM.
2. A score with a clear higher-is-better interpretation.
3. Potential headroom beyond current models.

…then my preferred design would be a Contact-inspired task about communicating to differently informed observers.

The key change would be to replace an observer’s unspecified real-world knowledge with an explicit information state that the evaluator can reason about exactly.

#### A concrete version

Generate a fictional world containing:

- A collection of possible target entities.
- Facts and relationships about them.
- A specified subset of information available to the receiver.
- A different subset available to the defender.
- A target known to the clue giver.
- A restricted set of allowed clue operations.

The model sees the target and both observers’ information. Its task is to construct a short, truthful clue that identifies the target for the receiver while leaving multiple possibilities for the defender.

For instance, it might be allowed to combine at most three statements about properties or relationships. The world should use randomized facts so that the model cannot substitute outside knowledge for the observers’ specified information.

A program then computes the candidates consistent with each observer’s information and the clue:

$$
C_R(c)=\{\text{target}\},\qquad |C_D(c)|\geq k.
$$

A successful clue uniquely identifies the target for the receiver while leaving at least k candidates for the defender.

The evaluator can check this directly. No reference LLM needs to decide whether the clue was understandable.

#### What would the score mean?

Possible scores are:

- The percentage of instances solved under a fixed clue budget.
- The smallest number of allowed clue operations needed for a valid solution.
- Performance on increasingly complex instances with verified solutions.
- The gap between the model’s clue length and the optimal clue length, where an optimizer can compute the latter.

This tests whether the model can construct communication that depends on differences between two observers’ information.

Difficulty can increase through the number of candidates, overlapping facts, relational depth, and restrictions on the clue. Finding a useful combination can be difficult even when checking a proposed combination is straightforward.

Two limitations should remain explicit.

First, this is a different task from ordinary-language Contact. It emphasizes reasoning about information and communication, with less emphasis on cultural knowledge, vocabulary, and spontaneous wordplay.

Second, candidate-set ambiguity is a guarantee relative to the specified inference rules. A fully strategic defender might also draw conclusions from why the sender chose this particular clue. If you want to claim resistance to that stronger defender, the evaluator must account for the sender’s policy as well. A simple candidate-set checker should be described as a defined logical observer.

I still think this is the most promising way to preserve Contact’s central idea while obtaining the kind of absolute scoring standard you want.

#### A simpler alternative preserves more natural language

You could use a fixed, independently constructed collection of:

- Revealed prefixes.
- Natural-language clues.
- Committed intended answers.

Then evaluate the model’s guesses directly. That gives an ordinary exact-answer benchmark without a participating reference LLM.

It preserves much of the decoding challenge, including indirect references and wordplay. It does not evaluate the full strategic clue-generation game.

For freely generated English clues, however, effectiveness for a particular audience requires either observing that audience or specifying a model of its behavior. Self-play supplies an audience, but makes that audience change whenever the evaluated model changes. The formal approach supplies a fixed, computable audience.

### 6. “Not saturated” needs a stronger test than scores below 100%

This is especially important for the self-play proposal.

There are three different reasons a benchmark can produce intermediate scores:

| Situation | Interpretation |
| --- | --- |
| The model makes avoidable mistakes and a feasible better strategy exists | Useful capability headroom |
| Randomness or information limits make some failures unavoidable | An intrinsic ceiling |
| Offense and defense improve together and continue cancelling each other | Stable competitive balance |

Only the first straightforwardly supports “higher scores will measure improved capability.”

For example, the simplified symmetric case with contact probability p(1 − p) has a maximum of 25%. A system achieving that maximum is not demonstrating 75 percentage points of room for improvement. Similarly, a self-play game that stays near 50% as both sides improve can look perpetually unsaturated while revealing little about their absolute progress.

Changing the turn limit until current models score 50% does not by itself create a useful benchmark. It might simply put the game at its balance point, or make success limited by information rather than reasoning.

For a benchmark with meaningful headroom, I would want:

1. A known feasible better performance level. A solver, constructive strategy, or verified solution establishes that the task can be done better.
2. Simple baselines that are genuinely weaker. Enumeration and randomized ambiguity should not already explain the achievable score.
3. A difficulty parameter that increases reasoning demands. More interacting constraints or deeper planning can do this; merely making the secret rarer may mostly test vocabulary.
4. An empirical pilot on current models. We cannot infer current saturation from the game’s apparent difficulty.
5. An error analysis. Failures should reflect the capability of interest, rather than mostly formatting mistakes or ambiguous instructions.

I cannot currently establish that natural Contact, or the proposed formal variant, has the required headroom. That needs measurement. A formal variant makes the diagnosis easier because you can distinguish avoidable errors from limits imposed by the rules.

### What I would recommend

Your desiderata lead to three coherent designs:

| Design | No participating reference LLM? | Clear higher-is-better skill score? | Preserves ordinary Contact? |
| --- | --- | --- | --- |
| Same-model Contact with a turn budget | Yes | Its outcome score measures balance; additional grounding is needed for skill | Largely |
| Fixed natural-language clue-solving benchmark | Yes | Yes, for decoding accuracy on that task distribution | Preserves one component |
| Formal selective-communication task or solvable game | Yes | Yes, using verified success or optimality gaps | Preserves the central communication problem, with substantial rule changes |

I would keep self-play Contact as a behavioral experiment and use a formally verifiable task for the main capability score. The self-play experiment could ask whether coordination increasingly outpaces interception as models change. The capability benchmark could ask whether models become better at constructing communications that exploit precisely specified differences in knowledge.

If preserving the original game is your highest priority, your proposed offense–defense balance curve is a defensible result in its own right. If a monotonic skill score and demonstrated frontier headroom are essential, I would make the task’s ground truth more explicit before investing in a large Contact evaluation.

---

## 06. User — Elo leaderboard

I just had another idea: rather than objective or absolute scores, how about if I publish an Elo leaderboard after having a variety of models play against each other under a term limit?

---

## 07. Assistant — Elo tournament design

Yes. **An Elo-style tournament is a good fit for Contact**, and it addresses the main problem with self-play: a model can demonstrate improvements in both offense and defense against other models. The ranking would be relative to the competing population, while the game outcomes would remain mechanically scored under your declared rules.

I would make one important adaptation: **each matchup should consist of two games with the roles reversed.** Then publish an overall rating alongside separate offensive and defensive ratings.

### 1. Make each matchup a pair of games

For models A and B, run:

| Game | Attacking team | Defender |
|---|---|---|
| First game | Two separate instances of A | One instance of B |
| Second game | Two separate instances of B | One instance of A |

Offense wins if it identifies the secret within the fixed turn limit. Defense wins if it survives that limit.

Use the same sampled secret and starting prefix in both games to match their difficulty, but start every participant in a fresh, isolated context. Otherwise, B could learn the secret while defending in the first game and carry that knowledge into its attacking role in the second.

Each model earns one point for winning a game in its assigned role:

- A wins on offense and defense: A wins the paired match, 2–0.
- Each model wins one game: the paired match is a draw, 1–1.
- B wins on offense and defense: B wins the paired match, 2–0.

Thus you have ordinary win/draw/loss results suitable for an Elo-style leaderboard.

For the initial benchmark, I would keep both attackers on the same model. Mixed-model attacking teams would be an interesting later experiment, but they introduce questions about teammate compatibility and which model deserves credit. With homogeneous teams, the competitor is clearly “model A’s complete Contact-playing system.”

Also, do not count the attacking team as having twice the model’s Elo. The two-instance offensive team and the one-instance defender are different roles in the game; every competing model gets to play both.

### 2. This gives you the “better at either role means a better score” property

Let $p_{AB}$ be the probability that A’s attacking team defeats B’s defender.

A’s expected normalized score in the paired matchup is:

$$
S_{AB}=\frac{p_{AB}+(1-p_{BA})}{2}.
$$

The first term measures A’s offensive success. The second measures A’s defensive success.

Therefore:

- Improving A’s offense increases $p_{AB}$, raising its score.
- Improving A’s defense decreases $p_{BA}$, also raising its score.

**Against an unchanged opponent, either improvement helps.** That is exactly the property missing from same-model self-play.

For example, if B’s offense defeats A’s defense 90% of the time, and B’s defense stops A’s offense 90% of the time, B earns an expected 90% of the points in their paired matches. It does not matter whether B’s own self-play happens to favor offense or defense.

Pairing the roles also accommodates a generally offense-favored game. If both models win their attacking games, the match is a draw. Neither receives an artificial advantage just from being assigned offense more often.

### 3. For publication, I would use a Bradley–Terry fit rather than sequential Elo updates

Ordinary Elo would be fine for an initial prototype. For a research leaderboard, I would estimate ratings from **all recorded games together**, rather than updating them chronologically using an arbitrary $K$-factor.

This has precedent in LLM leaderboards: the Chatbot Arena paper describes replacing its earlier Elo scores with Bradley–Terry coefficients because they were better suited to statistical estimation, and discusses uncertainty intervals for the resulting rankings. You would be using that statistical machinery with actual game outcomes. [arxiv.org](https://arxiv.org/html/2403.04132v1?utm_source=chatgpt.com)

For Contact, I would retain the individual game results and fit:

$$
P(\text{A’s offense beats B’s defense})=\sigma(\beta+a_A-d_B),
$$

where:

- $a_A$ is A’s **offensive strength**.
- $d_B$ is B’s **defensive strength**, with higher values indicating better defense.
- $\beta$ captures the game format’s general offensive advantage.
- $\sigma$ is the logistic function.

This lets the data distinguish a model with excellent defense and mediocre offense from one with the opposite profile.

You can then publish three columns:

| Rating | Meaning |
|---|---|
| **Overall** | Strength across equally weighted offensive and defensive roles |
| **Offense** | Ability of two copies to defeat other models’ defenders |
| **Defense** | Ability of one copy to resist other models’ attacking teams |

Under this additive model, a natural overall strength is:

$$
r_A=\frac{a_A+d_A}{2}.
$$

This average has a useful justification: **under the model, $r_A>r_B$ exactly when A’s expected score in a paired, role-reversed matchup exceeds 50%.**

You can express these strengths on a familiar Elo scale. I would describe the headline number as an *Elo-scaled overall rating*, and use the full two-role model when predicting matchup probabilities.

For a first release, you could also use ordinary Elo on the paired match results and report separate offensive and defensive win rates. The two-role statistical model is a refinement, not a prerequisite for finding out whether the game is useful.

### 4. Elo helps with your saturation concern, but the underlying game still needs to discriminate

A relative leaderboard has a useful property: **new models can keep demonstrating progress by defeating previous models**, without needing a larger maximum score on a fixed question set.

But Elo cannot manufacture meaningful differences if the game becomes uninformative. For example:

- If the turn limit is so generous that every attacking team wins, nearly every paired match is a draw.
- If the limit is so short that every defender survives, nearly every paired match is also a draw.
- If all strong models implement effectively equivalent strategies, ratings will mostly reflect sampling noise.

So I would choose the turn limit using a development pilot, then freeze it before the main evaluation.

The pilot should establish that:

1. The results contain informative differences among models.
2. Those differences persist on new secret words.
3. The ranking is reasonably stable under nearby turn limits.
4. Simple enumeration and deliberate-ambiguity strategies do not already explain almost all performance.

You do not need exactly a 50% overall offensive win rate. The aim is a format that distinguishes competitive strength, rather than one that simply yields balanced aggregate outcomes.

Changing the turn limit later should count as changing the benchmark version. A model that is strong with five attempts might have a different relative advantage with fifty.

### 5. Keep the matchup matrix alongside the leaderboard

A scalar rating is a summary. Contact could produce specific compatibility effects:

- A might be particularly good at decoding B’s clues.
- B might be particularly good at decoding C’s.
- C might exploit associations that A consistently misses.

That can produce cycles or other patterns that one number cannot represent faithfully. This is a recognized limitation of Elo-style evaluation in multiagent games. [arxiv.org](https://arxiv.org/abs/1909.09849?utm_source=chatgpt.com)

I would therefore publish both:

- The leaderboard, for an accessible overall comparison.
- The model-by-model outcome matrix, for the actual matchup structure.

You can check whether the fitted ratings predict the observed matchups reasonably well. If they do, the scalar ranking is a useful summary. If there are large, reproducible exceptions, those exceptions may themselves be an interesting finding.

I would not start by adopting a more complicated ranking system to solve hypothetical cycles. First collect the matrix and see whether they matter.

### 6. A few protocol choices will matter more than the rating formula

#### Define a turn precisely

I would count one complete clue attempt as a turn: the giver commits a word and clue, the other players submit their responses, and the program resolves the outcome.

Specify how direct guesses, failed contacts, and invalid moves consume the budget. Otherwise, different retry behavior can give models different effective turn limits.

Keep the private commitments and information barriers from the earlier design. Elo aggregates results; it does not resolve ambiguity in the rules.

#### Have the environment choose the secret

Sample secrets from a declared distribution rather than letting defenders choose them.

That makes matched games easier to compare and avoids conflating defensive skill with choosing unusually obscure words—or with an opponent’s ability to predict a model’s favorite secret words.

#### Fix the resources and the model configuration

A leaderboard entry should identify:

- The exact model version.
- Its prompts and reasoning settings.
- Available tools.
- The inference budget.
- The game rules and legal vocabulary.

Giving the same budget to each participant is a reasonable starting convention. It gives offense two instances and defense one, but every model receives both assignments across the paired matchup. An equal-total-budget-per-side experiment could be a useful secondary analysis.

#### Show uncertainty

Publish confidence intervals or rank uncertainty, rather than treating every small numerical difference as a firm ordering.

Because matched games share a secret, uncertainty estimates should preserve that pairing. If the same secrets are reused across many model pairings, account for that shared difficulty as well. Individual turns within a game should not be treated as independent benchmark samples.

#### Preserve an anchor across releases

Elo values are relative to the player population and an arbitrary numerical origin. If you want to discuss progress over time, retain fixed historical model configurations as anchors and keep the protocol consistent.

Otherwise, a rating change could reflect a changed opponent pool or changed normalization.

### 7. A manageable first experiment

I would begin with a small round robin across several model families.

For example:

- **6 model configurations**
- **10 sampled secrets per unordered model pair**
- **2 games per secret, with roles reversed**

That gives:

$$
\binom{6}{2}\times10\times2=300\text{ games}.
$$

That is a development pilot, not necessarily enough for precise rankings. It should be enough to reveal gross role imbalance, common protocol failures, and whether there are promising differences worth measuring more carefully.

The cost can be larger than the game count suggests. If each attempt uses three completions and the cap is 20 attempts, 300 games could require up to roughly **18,000 completions**, with fewer when games end early. I would settle the basic rules on a smaller run before scaling up.

For the published results, I would include the overall and role-specific ratings, uncertainty, matchup matrix, exact configurations, transcripts, and scoring code.

**I would pursue this tournament design.** It gives Contact a coherent evaluation target: *competitive communication under a fixed resource budget*. Paired role swaps let both offensive and defensive improvements contribute positively, while the empirical pilot can determine whether the game produces stable, informative distinctions among current frontier models.

---

## 08. User — Direct guesses and brute-force baseline

I've just realized I forgot to mention something earlier. For the attackers, a legal turn can consist of simply guessing some word directly rather than giving their partner a clue. If that word is the target word then the attackers win. (The downside of doing this is that it will likely be wrong, and then you cannot use it as a word to match with your teammate on future turns to reveal more prefix letters.) So there is a natural skill floor which is a brute-force strategy of filtering the dictionary to words consistent with the prefix and guessing them one at a time in alphabetical order. So the benchmark should measure how much faster you win than you would by using a brute-force strategy.

---

## 09. Assistant — Direct guesses and brute-force baseline

**Yes—this clarification gives you an exact, defender-independent baseline, and makes search efficiency a natural primary metric.** Alphabetical guessing no longer requires the attackers to communicate any clues successfully: it is a legal strategy that the evaluator can calculate directly.

I would combine this with your tournament idea: **publish speedup over brute force as an interpretable performance measure, and use paired games to rank models competitively.** There are two scoring details worth getting right: how to aggregate speedups, and how to handle games that reach the turn limit.

### 1. The brute-force baseline is exactly calculable

Let $V_p$ be the alphabetically sorted list of legal secret words consistent with the **initially revealed prefix** $p$.

For a secret word $s$, define:

$$
B(s)=\operatorname{rank}_{V_p}(s),
$$

with the first word having rank 1.

Then alphabetical brute force takes exactly $B(s)$ guesses. You can calculate that without running any models.

**Keep this baseline fixed from the initial state.** You should not give it the extra prefix letters earned by the evaluated attackers; earning those letters is precisely the benefit you want to measure.

#### Uniformly sampled secrets make the comparison especially clean

If the secret is sampled uniformly from $N$ initial candidates, then:

$$
\mathbb{E}[B]=\frac{N+1}{2}.
$$

Moreover, **every strategy that only makes nonrepeating direct guesses has that same expected cost**, provided its only feedback is whether each guess is correct. Alphabetical order, reverse-alphabetical order, and a model’s preferred ordering all have the same expectation.

That gives you a strong interpretation: under uniform sampling, a sustained reduction in mean turns must come from acquiring additional information through the Contact mechanics, rather than merely choosing a better ordering of guesses.

If instead you sample common words more frequently, a model can beat alphabetical order by guessing common words first. That is a legitimate search improvement, but it does not demonstrate skill at making contacts. In that setting I would additionally compare against probability-ordered guessing, or run an ablation where the same model is allowed only direct guesses.

### 2. Aggregate turns first, then calculate the speedup

For games that all finish, the natural headline metric is:

$$
\boxed{\text{Speedup}=\frac{\text{total brute-force turns}}{\text{total model turns}}=\frac{\sum_i B_i}{\sum_i T_i}}
$$

A score of $4\times$ means the model used one quarter as many turns across the evaluated games—a 75% reduction.

**Do not take the arithmetic mean of individual-game ratios $B_i/T_i$.** That can manufacture apparent improvements from nothing more than changing the guessing order.

For example, suppose there are two equally likely secrets:

| Strategy | Turns for first secret | Turns for second secret | Mean turns |
|---|---:|---:|---:|
| Alphabetical | 1 | 2 | 1.5 |
| Reverse alphabetical | 2 | 1 | 1.5 |

Averaging the per-game speedups gives:

$$
\frac12\left(\frac12+\frac21\right)=1.25,
$$

which misleadingly suggests a 25% improvement. Taking the ratio of total turns correctly gives:

$$
\frac{1+2}{2+1}=1.
$$

You could also report **mean turns saved** or **the fraction of total baseline turns saved**. Those are straightforward to interpret.

### 3. A brute-force fallback would solve the turn-limit problem particularly well

If you stop a game after $L$ turns without a win, you do not know how many turns the model would eventually have needed. Assigning the timeout a completion time of $L$ would be misleading.

For example, a model that never solves the word could appear “50 times faster” than a 1,000-guess baseline simply because you stopped it after 20 turns.

Your direct-guess rule offers a clean solution:

> **Let the model play for at most $L$ turns. If it has not won, finish by alphabetical guessing from the remaining possible secret words.**

The evaluator knows the secret and can calculate the exact cost of that fallback **without additional model calls**.

Let $R_i$ be the secret’s alphabetical rank among the remaining candidates at the end of the model-controlled phase. Define the effective completion cost:

$$
C_i=
\begin{cases}
T_i, & \text{if the model wins within }L\text{ turns},\\
L+R_i, & \text{otherwise}.
\end{cases}
$$

Your headline speedup becomes:

$$
\boxed{\text{Speedup}=\frac{\sum_i B_i}{\sum_i C_i}}
$$

This measures a precisely specified strategy: **up to $L$ turns of model play, followed by deterministic enumeration.** It does not pretend to estimate what the model itself would have done after the limit.

#### Why this works well

Suppose the initial secret has alphabetical rank 300, and the model gets 10 turns:

| What happens during the model phase | Remaining alphabetical rank | Effective total cost |
|---|---:|---:|
| Solves on turn 6 | — | 6 |
| Earns useful prefix letters but does not solve | 4 | $10+4=14$ |
| Earns no letters and eliminates no candidates | 300 | $10+300=310$ |
| Simply makes the first 10 alphabetical guesses | 290 | $10+290=300$ |

This gives useful prefix discovery credit even when the model has not finished by the cap. It also penalizes wasted turns.

And it has a desirable exact anchor: **a model that follows alphabetical brute force receives a speedup of $1\times$ on every evaluation set**, including games that reach the cap.

The fallback must use only information legitimately available to the attackers:

- The current revealed prefix.
- Failed direct guesses.
- Any other words publicly confirmed not to be the secret under your rules.

It must not eliminate candidates merely because the evaluator privately knows they are wrong. The evaluator’s knowledge of the secret is used only to calculate its position in the predetermined fallback sequence.

I think this is a particularly useful scoring design for your benchmark: it keeps model-inference costs bounded while providing an exact completion cost for every game.

### 4. This combines cleanly with the Elo tournament

For the same secret, run the two directions in fresh contexts:

- A’s attackers against B’s defender, producing effective cost $C_{AB}$.
- B’s attackers against A’s defender, producing effective cost $C_{BA}$.

If the goal is efficiency, define the paired result as:

- **A wins** if $C_{AB}<C_{BA}$.
- **B wins** if $C_{BA}<C_{AB}$.
- **Draw** if the costs are equal.

This retains the property we wanted:

- Better offense reduces a model’s own attacking cost.
- Better defense increases its opponent’s attacking cost.
- Both improvements help its paired result.

Because both games use the same secret and initial prefix, their brute-force baseline is identical. Comparing their speedups therefore gives the same winner as comparing their completion costs.

This would distinguish cases that the previous deadline-only tournament treated as draws. If both attacking teams win, but A solves in 5 turns and B in 15, A wins the efficiency comparison. If neither finishes within the model budget, the fallback distinguishes useful progress from unproductive play.

That would be a deliberate change to the competitive objective: the defender’s job becomes delaying discovery as much as possible during the model-controlled phase, rather than merely surviving to the deadline. I would state that explicitly in the rules.

The leaderboard could then show:

| Statistic | What it communicates |
|---|---|
| Overall Elo-style rating | Competitive performance in paired efficiency contests |
| Offensive speedup over brute force | How much search effort the attacking system saves |
| Mean effective completion cost | The underlying quantity before normalization |
| Win rate within the model budget | How often the model finishes without fallback |

The offensive speedup should be evaluated against a declared opponent distribution—for example, equal weight on each other model in the tournament. The baseline itself does not depend on a defender, but the model’s improvement over it still does. A weak defender can make large speedups easier.

### 5. The retirement rule adds a strategic choice

The attackers now have two ways to spend a turn:

- Direct guess: test one candidate with certainty.
- Contact attempt: try to obtain information that could eliminate many candidates.

A wrong direct guess also consumes that word’s future value as a contact word. That creates a decision about whether to test a candidate now or preserve it as a useful communication opportunity.

For example, an unlikely secret that the teammate would recognize but the defender might miss could be valuable as a contact word. Burning it on a low-probability direct guess could be poor play. Conversely, a plausible secret that is difficult to clue reliably may be worth guessing directly.

One qualification: if a word can be clued with perfectly reliable teammate decoding at the same turn cost, cluing it may be at least as good as directly guessing it. It preserves the chance of finding the secret and adds the possibility of earning a prefix letter. Direct guessing becomes attractive when coordination is uncertain, clue restrictions matter, or the direct action costs less inference.

That suggests a useful analysis for the paper: when do models guess directly, when do they attempt contacts, and does that choice improve efficiency? A no-contact ablation would help establish how much performance comes from the game’s communication mechanism.

### 6. A few details would keep the score meaningful

**Call the main measure turn efficiency.** A scripted dictionary loop can make guesses cheaply, while a contact attempt may require three model completions. A reduction in turns is not necessarily a reduction in inference cost or wall-clock time. Report those costs separately.

**Use the secret’s baseline rank only for scoring.** Do not reveal it or set a publicly visible turn limit based on it; that could leak the secret’s position in the dictionary. A global limit, or one based only on public information such as the initial number of candidates, avoids this.

**Be explicit about weighting.** A ratio of total turns measures total effort saved, so large search spaces contribute more than small ones. That is defensible, but I would also report results by initial candidate-set size.

**Keep the simple contact strategies as baselines.** A large improvement over direct guessing does not by itself demonstrate frontier-level difficulty. Deliberately ambiguous clues might also reduce a large candidate set efficiently. The pilot still needs to show that current models make meaningful, reproducible differences beyond those strategies.

My preferred version is now: a fixed budget of model play, exact alphabetical fallback, aggregate speedup over initial brute force, and Elo from paired completion-cost comparisons. That gives you both an understandable score—how much search effort is saved—and a competitive ranking that rewards better offense and better defense.

---

## 10. User — Alphabetical scoring bias

Nitpick: should we have the resolver use random order for the remaining letters instead of alphabetical? If the players know that they're graded by how far in the alphabet the word continues, wouldn't it be advantageous to skew your guesses towards words where the remaining letters are later in the alphabet, so if you're wrong and run out of turns, the words you haven't guessed are slightly earlier in the dictionary so your measured speedup looks larger? Is this effect negligible?

---

## 11. User — Forward and backward averaging

Actually, maybe we should just compute the remaining fallback score twice, once backwards and once forward, and average the two?

---

## 12. Assistant — Forward and backward averaging

Yes. **Averaging forward and backward fallback costs gives exactly the expected cost of a uniformly random ordering—without introducing randomness.** You can simplify it further and calculate the result directly.

If there are $n$ remaining candidate words and the secret has position $r$ in alphabetical order, then:

- Forward enumeration takes $r$ guesses.
- Reverse enumeration takes $n+1-r$ guesses.

Their average is:

$$
\frac{r+(n+1-r)}{2}=\boxed{\frac{n+1}{2}}.
$$

The secret’s position cancels completely. You do not need to simulate either enumeration.

### The resulting scoring rule

Let:

- $N_i$ be the number of possible secret words at the start of game $i$.
- $L$ be the model’s turn budget.
- $n_i$ be the number of remaining candidates if the model reaches that limit.
- $T_i$ be the actual winning turn, if it finishes within the limit.

Symmetrize the initial brute-force baseline as well:

$$
B_i=\frac{N_i+1}{2}.
$$

Then score the model’s effective completion cost as:

$$
C_i=
\begin{cases}
T_i, & \text{if it solves within the budget},\\
L+\dfrac{n_i+1}{2}, & \text{otherwise}.
\end{cases}
$$

And calculate aggregate speedup using:

$$
\text{Speedup}=\frac{\sum_i B_i}{\sum_i C_i}.
$$

**Average the enumeration costs before calculating speedup.** Averaging two speedup ratios would not generally produce the same answer.

For example, with 100 candidates remaining after 20 model turns, every unsolved game gets an effective cost of:

$$
20+\frac{100+1}{2}=70.5.
$$

It no longer matters whether the actual secret happens to be first or last in the remaining dictionary. Under alphabetical fallback those two cases would have scored 21 and 120 turns, despite having the same number of unresolved candidates.

### What this fixes

Your proposal removes the incentive to care about alphabetical position in the fallback. A failed direct guess reduces the remaining candidate count by one, regardless of which word was guessed. A successful contact gets credit according to how many candidates the newly revealed prefix eliminates.

There is one qualification to the original concern: with uniformly sampled secrets and correctly aggregated turn costs, simply guessing late words first would not improve average pure-guessing performance. Any nonrepeating guessing order has expected completion time $(N+1)/2$. The large gains on some secrets would be offset by losses on others.

But alphabetical position still creates unnecessary variation in individual results, potentially substantial variation when many candidates remain. Your forward/backward average removes that dependence entirely.

For the paired tournament, you can compare these expected completion costs in the two directions, with lower cost winning and equal costs drawing. That evaluates expected search efficiency; it does not require playing out randomly ordered fallback guesses.

I would adopt this revision. The scoring rule becomes especially simple: **turns already spent, plus half the remaining candidate count rounded upward by the $+1$ convention**—more precisely, $L+(n+1)/2$, allowing fractional expected costs.

---

## 13. User — Specification and overall project

Great. I want to give this to Codex to build the benchmark; please make a specification document I can give it that explains the game mechanics and benchmark requirements. Then I'll run it on some models (I have OpenAI, Claude, and Gemini API keys) to get results, write a paper, and publish it on arxiv and the leaderboard on a website. Also give me a to-do checklist for the overall project (not just Codex's implementation part).

---

## 14. Assistant — Specification and project checklist

I’ve created both documents as Markdown files you can put directly into a Codex repository.

[CONTACT_BENCHMARK_SPEC.md](CONTACT_BENCHMARK_SPEC.md)

The complete implementation handoff: game mechanics, information boundaries, scoring, tournaments, provider integrations, logging, statistical analysis, acceptance tests, and the static leaderboard. It includes a worked game, example configuration, and five implementation milestones.

[CONTACT_PROJECT_CHECKLIST.md](CONTACT_PROJECT_CHECKLIST.md)

The overall project plan: 96 checkboxes across 14 phases, covering research design, implementation, experiments, the paper, reproducible release, arXiv, website publication, and maintenance. It distinguishes your responsibilities from Codex’s.

### What the specification settles

The specification is concrete enough for Codex to implement without reconstructing our conversation. It separates the rules you supplied from proposed version 0.1 defaults for details we had not resolved.

The important defaults are:

| Detail | Proposed behavior |
|---|---|
| Attacking turns | Alternate the two attacker instances; each chooses a direct guess or a clue. |
| Response timing | Receiver and defender each submit one sealed answer before either answer is disclosed. |
| Reusing clue words | Retire the intended word after every valid clue attempt. |
| Retired words versus eliminated targets | Keep these separate: a failed clue can retire a word without proving that it is not the secret. That word remains available for a direct guess. |
| Defender answers | Publish successful blocks; keep nonblocking raw answers private so they cannot accidentally disclose the secret. |
| One remaining candidate | Require an explicit winning action, consistent with one remaining fallback guess. |
| Word endings | Use an explicit end-of-word reveal to handle cases such as `art` versus `artist`. |
| Clue legality | Start with precisely defined mechanical checks; treat semantic appropriateness as a separate research condition or audit. |

That last choice deserves attention before freezing the study. **Objective outcome scoring is straightforward; objectively enforcing “a proper semantic clue” is a separate problem.** The initial implementation therefore makes its permitted communication rules explicit and includes simple encoding and ambiguity strategies among the baselines. The pilot should establish whether that version measures something interesting.

The document also closes several implementation loopholes. For example, malformed responses cannot be echoed into public history as an unlimited communication channel, and the private intended word cannot leak through a response schema or a specially filtered dictionary list.

### The scoring method is fully specified

Your forward-and-reverse averaging proposal is implemented analytically.

For initial candidate count $N$, turn limit $L$, winning turn $t$, and remaining candidate count $n$:

$$
B=\frac{N+1}{2},
\qquad
C=
\begin{cases}
t, & \text{if solved within the limit},\\
L+\frac{n+1}{2}, & \text{otherwise}.
\end{cases}
$$

The overall efficiency statistic is:

$$
\text{Aggregate speedup}=\frac{\sum_i B_i}{\sum_i C_i}.
$$

The specification requires exact half-turn arithmetic internally, with no rounding and no simulated fallback calls. It also prohibits averaging individual speedup ratios, which can produce misleading apparent improvements.

The interpretation is precise: this measures the completion effort of model play followed by the specified brute-force resolver. It does not claim to predict how long the model would take if allowed to continue indefinitely.

### I kept Elo alongside efficiency

The leaderboard uses your paired competition:

- A+A attack B.
- B+B attack A.
- Both legs use the same secret and fresh, isolated contexts.
- The model with the lower attacking completion cost wins the paired contest.

The specification then fits a batch Elo-style rating, with uncertainty intervals and the underlying matchup matrix.

One important finding from the review is that winning more paired contests and saving more turns on average are different objectives. Even two direct-guessing strategies with identical average cost can earn different match scores: one can win narrowly on several words and lose badly on another.

Accordingly, the website must expose both:

- **Efficiency:** aggregate speedup and mean completion cost.
- **Competition:** paired Elo-style rating.
- **Overall cost advantage:** how many turns a model saves on offense and imposes on opponents through defense.
- **Diagnostics:** offense, defense, deadline success, invalid actions, and inference expenditure.

This preserves the Elo leaderboard while making its interpretation defensible in the paper.

### What Codex is being asked to build

The implementation is divided into five milestones:

1. **Deterministic engine and scorer.** Exact rules, role-specific observations, vocabulary handling, worked fixtures, and mathematical tests.
2. **Baselines and tournament runner.** Scripted policies, paired scheduling, logs, checkpoints, resume, and offline replay.
3. **OpenAI, Claude, and Gemini integrations.** Separate adapters, validated settings, structured responses, usage accounting, rate limits, and bounded retries.
4. **Analysis pipeline.** Aggregate efficiency, paired ratings, target-cluster bootstrap intervals, matchup matrices, and paper-ready figures.
5. **Static leaderboard and release package.** Sanitized exports, replay examples, methodology, local preview, and deployment instructions.

The provider guidance is dated and linked to official documentation. In particular, the handoff avoids assuming that every provider accepts the same sampling parameters, and it accounts for Google’s current recommendation to use the Interactions API for new development. [Claude Platform … +1](https://platform.claude.com/docs/en/build-with-claude/thinking?utm_source=chatgpt.com)

The implementation must work end to end with offline fixtures before credentials are needed. Live execution is a separate command with explicit request or spending limits.

### Your overall project checklist

The companion file contains the detailed checklist. These are the main stages and their completion criteria.

#### 1. Establish the research contribution

- Write down the abilities you intend to measure: coordination, clue interpretation, blocking, search efficiency, or a specified combination.
- Review the existing Contact proposals and prototypes, plus related game benchmarks.
- Frame novelty around what the completed work actually adds: the protocol, scoring method, evaluation design, results, and released artifacts.

Completion criterion: a clear research question and a supported explanation of how this project differs from prior work.

#### 2. Choose the lexicon and development protocol

- Select a lexicon with documented provenance and usable redistribution terms.
- Freeze normalization, allowed word forms, and the distinction between secret and contact vocabularies.
- Review the proposed defaults above.
- Define the target distribution and development/evaluation separation.

The default design uses independent development and evaluation draws from the same declared word distribution. If you prefer disjoint word supports, the candidate counts and baseline must reflect those supports.

Completion criterion: a versioned protocol and dictionary manifest from which the same games can be reconstructed.

#### 3. Have Codex implement and validate the offline system

- Build the engine, scorer, baseline policies, and replay first.
- Verify all consequential state transitions and information boundaries.
- Exhaustively check the scoring on tiny dictionaries.
- Run a complete scripted tournament through analysis and website generation.

Completion criterion: the whole pipeline works without API keys, and scores can be regenerated from logs.

#### 4. Verify the three provider integrations

- Select exact model configurations and supported reasoning settings.
- Run a small, budgeted smoke test for each provider.
- Check structured output, refusals, truncation, usage accounting, and recovery from interruption.
- Measure prompt growth and actual token use.

Completion criterion: the selected models can play valid games, and their resource use is understood well enough to budget the pilot.

#### 5. Run a pilot that tests difficulty and validity

- Compare several turn limits and difficulty strata.
- Include direct-only model play and inexpensive scripted strategies.
- Examine ambiguity and dictionary-index strategies.
- Inspect representative successes, failures, and surprising results.
- Check whether strong models separate meaningfully and retain headroom.

This is the main research gate. A working implementation does not establish that the benchmark is useful. If cheap strategies dominate, all models saturate, or results mostly reflect output-format failures, use the development phase to revise the protocol or narrow the claims.

Completion criterion: evidence that a larger experiment can answer a worthwhile question.

#### 6. Freeze the confirmatory study

- Freeze rules, prompts, lexicon, model settings, turn cap, baseline suite, and code revision.
- Choose sample size from pilot variability and your desired precision.
- Keep task counts and repetitions balanced across model pairs.
- Prespecify missing-data handling, infrastructure reruns, uncertainty calculations, and exploratory analyses.
- Finalize the budget before starting held-out runs.

Completion criterion: a run manifest and analysis plan that do not depend on seeing the final rankings.

#### 7. Execute, reconcile, and audit the experiments

- Interleave pairings across time.
- Monitor quotas, costs, failures, and completion.
- Recover incomplete games according to the fixed policy.
- Replay every scored game.
- Freeze raw and analysis-ready data snapshots.

For budgeting, the specification includes the scaling calculation: six models and ten tasks per unordered pair produce 300 raw games. At a 20-turn cap, an all-clue run could require up to 18,000 game decisions before transport retries. Smoke tests should establish the token costs before scaling to that size.

Completion criterion: every reported result traces to a complete transcript and a reproducible computation.

#### 8. Analyze the results and write the paper

- Report efficiency, competitive ratings, role-specific behavior, uncertainty, and resource use.
- Include the pairwise matrix so the scalar ranking does not conceal matchup effects.
- Compare full play with direct-only and scripted baselines.
- Investigate disagreement between Elo and mean efficiency.
- Separate confirmatory findings from exploratory observations.
- Regenerate all numerical tables and figures from the frozen analysis export.

The checklist proposes a paper structure covering motivation and related work, game mechanics, scoring derivation, experimental protocol, results, ablations, limitations, and reproducibility.

Completion criterion: each claim is supported by an experiment or clearly identified as a limitation or hypothesis.

#### 9. Prepare the reproducible release

- Release the engine, scorer, prompts, configurations, baselines, and analysis code.
- Include a small offline demonstration.
- Document licenses separately for code, lexicon, data, and other assets.
- Provide enough data to reproduce the published analysis without paid model calls.
- Tag and archive the version used in the paper.

Completion criterion: another researcher can reproduce the analysis in a fresh environment.

#### 10. Submit to arXiv

- Check your account and possible endorsement requirements early.
- Prepare the metadata, category choice, license, and submission package.
- For a LaTeX paper, include the source and required figures.
- Inspect the PDF compiled by arXiv before completing submission.
- Add the eventual identifier and version to the release and website.

arXiv may require endorsement for a new submitter or category, and its instructions require TeX source when the paper was produced using TeX/LaTeX. [arXiv info +2](https://info.arxiv.org/help/submit/index.html?utm_source=chatgpt.com)

#### 11. Publish and maintain the leaderboard

- Publish the static site from the same versioned export used for the paper.
- Show uncertainty, sample counts, model settings, and protocol versions.
- Keep efficiency and competitive rating as distinct views.
- Include methodology, baselines, matchup matrices, data downloads, and paper/code links.
- Define how new models, changed APIs, corrections, and new protocol versions enter the leaderboard.
- Preserve dated snapshots as the evaluated population changes.

Completion criterion: readers can understand what the ranking means, inspect the evidence, and reproduce or challenge it.

### Suggested first instruction to Codex

Put both files in the repository root and give Codex this:

> Implement `CONTACT_BENCHMARK_SPEC.md`, using `CONTACT_PROJECT_CHECKLIST.md` as the broader research roadmap. Follow the five implementation milestones and the proposed version 0.1 defaults. Start with the deterministic engine, exact scorer, scripted baselines, and offline acceptance tests, then complete the provider adapters, analysis pipeline, and static leaderboard. Record any departures from the specification. Make paid execution an explicit command with a budget I supply.

The most consequential decision after implementation will be the pilot: whether this version of Contact shows useful gains over simple strategies while leaving enough headroom for stronger models.

---

## 15. User — Public clues, private commitments, and blocking

Wait -- based on your "retired words versus eliminated targets" detail, I think we need to clarify the rules and setup. I do not think "a failed clue can retire a word without proving that it is not the secret".

When I play Contact in real-time with humans, we usually play with a rule that, if any player says the target word at any time, the guessers instantly win. But this rule is unusable without a clue length limit, otherwise an AI can trivially output the contents of the dictionary as its first "clue" and instantly win on the first turn.

Perhaps how this should work is:
One copy of the model forming the guesser team is assigned the role of guesser 1 and the other copy is assigned the role of guesser 2.
On each turn: Guesser 1 publicly announces its clue and privately registers its intended word. Guesser 2 privately registers what word it thinks the clue refers to. [Perhaps we should capture its probability distribution? Might be interestingly informative or scoreable.] The defender is allowed to read the clue and block any number of words from the dictionary that it thinks the guessers might match on, perhaps even blocking zero words if it thinks the clue is uninformative/bad and the guessers won't make contact. (If anyone, including the defender, says the target word, the defender loses, so they would never choose to emit it in the blocklist.) [Here too we might want to ask the defender model for its probability distribution of what it thinks the clue refers to. Maybe we can give models a defender skill rating based on what probability they assign to guesser 1's intended word, and give models a clue-giving skill rating involving guesser 2's ability to know what guesser 1 meant.]
If either guesser's guess was the target word, or if the target word was mentioned in the clue or the blocklist, the guessers win. Otherwise, the game continues, and every word emitted so far is no longer an eligible contact word (guessers can't earn a prefix letter by matching on that guess).

With that in mind, how should we adjust the rules and the spec document?

---

## 16. User — Two guesses per turn

I forgot to mention that this change would raise the floor of the brute-force strategy: under this rule, you can trivially win in n/2 turns starting from a prefix that has n legal completions with the strategy that guesser 1 selects the alphabetically first legal completion and guesser 2 selects the last.

---

## 17. User

I forgot to mention that this change would raise the floor of the brute-force strategy: under this rule, you can trivially win in n/2 turns starting from a prefix that has n legal completions with the strategy that guesser 1 selects the alphabetically first legal completion and guesser 2 selects the last.

Also, clarification to the procedure I just said: after the defender emits their blocklist, the guessers' guesses are not revealed if both of their guesses were blocked (the defender is not informed what guess they intended); if one clue was blocked, the remaining guesser has the option to cancel the contact attempt and not reveal their guess. (For example, you might want to do this if you think your guess is a more valuable word to use for a subsequent clue to earn a letter than as a direct guess.)

---

## 18. Assistant

Yes—the first/last strategy guarantees a win within **$\lceil n/2\rceil$ turns**, and that guarantee survives your cancellation rule, provided the brute-force policy **always chooses to reveal when offered the choice**. Each selected word is then either revealed by a guesser or already publicly named in the defender’s blocklist.

Your disclosure clarification changes the procedure substantially. I’ve updated both documents to **v0.3**, with one interpretation explicitly marked as proposed:

- [CONTACT_BENCHMARK_SPEC.md](CONTACT_BENCHMARK_SPEC.md)
- [CONTACT_PROJECT_CHECKLIST.md](CONTACT_PROJECT_CHECKLIST.md)

### 1. The important distinction is between registering a word and revealing it

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

### 2. The revised reveal procedure

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

### 3. A blocked word is used up; a canceled, unspoken word is preserved

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

$$
U_{\text{new}}
=
U_{\text{old}}
\;\cup\;
\{\text{dictionary words mentioned in the clue}\}
\;\cup\;
\{\text{blocklist words}\}
\;\cup\;
\{\text{actually revealed guesses}\}.
$$

**Unrevealed commitments are not added to that set.**

Cancellation cannot undo another public mention. If Guesser 2’s word was literally present in the clue, canceling its later revelation does not preserve it—the clue already used it.

This also means the engine must not silently remove canceled words from the next turn’s public candidate list. Doing so would both misapply the rules and expose the hidden word through the difference between successive lists.

### 4. The defender’s feedback needs careful specification

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

### 5. The stronger brute-force baseline remains valid

For the first/last policy, each chosen endpoint has two possibilities:

- It is blocked, in which case the defender has publicly emitted it.
- It is unblocked, in which case the baseline reveals it.

Thus every surviving turn eliminates at least two candidates whenever at least two remain. A defender cannot avoid this by blocking the target, because saying the target in the blocklist itself loses.

The worst-case guarantee is:

$$
T\leq \left\lceil\frac n2\right\rceil.
$$

For a uniform target with an empty blocklist and no additional eliminations, the expected completion time is:

$$
F_2(n)=
\begin{cases}
\dfrac{n+2}{4}, & n\text{ even},\\[6pt]
\dfrac{(n+1)^2}{4n}, & n\text{ odd}.
\end{cases}
$$

So with 100 candidates, this strategy has a **50-turn worst case** and a **25.5-turn mean**. Extra defender blocks can make it faster by eliminating additional candidates.

The same reasoning preserves the capacity-matched baseline from the previous draft. If a clue may literally name up to $k$ additional live candidates, a scripted policy can still test up to $b=k+2$ attacker-selected candidates per turn, provided it always reveals when given the option. The proposed $k=4$ restriction remains an additional benchmark design choice, not a rule you have already specified.

#### The fallback formula does not need to change

For a uniformly shuffled ordering tested in batches of $b$, retain:

$$
F_b(n)=\frac1n\sum_{r=1}^{n}\left\lceil\frac rb\right\rceil.
$$

For an unresolved game, the cost remains:

$$
C=L+F_b(n),
$$

where $n$ is computed from the **public state after fully resolving the last turn**, including any reveal/cancel decision. Hidden commitments do not reduce $n$.

There is also a useful behavioral check: **on the final model turn, revealing weakly dominates canceling under this objective**. A correct reveal wins immediately; an incorrect reveal cannot increase the fallback cost; and there are no remaining model turns in which to use the preserved word for contact. Earlier in the game, preservation can have future value.

### 6. What changed in the implementation requirements

The revised specification now includes the conditional reveal table, private versus public state, cancellation schemas, worked examples, and regression cases—including a canceled commitment that happens to equal the secret.

Operationally, a clue turn can now require **up to four model decisions**: Guesser 1, Guesser 2, the defender, and the conditional reveal/cancel choice. The runner must distinguish those phases when saving and resuming a game, because one guesser can act twice within the same turn.

The project checklist now includes cancellation ablations, later reuse of preserved words, checks for accidental disclosure through logs and candidate lists, and the revised call budget. I also checked the brute-force guarantees and disclosure transitions on exhaustive small cases.

The one interpretation to settle before implementation is the target-hit timing. **My recommendation is that a canceled, unrevealed commitment to the target does not win**, and that is the explicitly labeled proposed default in v0.3.

---

## 19. User

"Privately registering a word does not itself test whether it is the target. A registered word becomes a target guess only when it is publicly revealed." Yes, this is what I meant all along. "Privately registering" a guess is analogous to thinking it silently in the real-life version of Contact, and you only win if you guess it aloud.
"Under the earlier rule, a canceled word can still be preserved for future contact, but a surviving player privately learns that their word was **not** the target." Right, this earlier misinterpretation is definitely not the intended mechanic. You cannot win at Contact by silently thinking the answer. You can only win by directly saying or guessing the word or by earning the last letter by making contact when there is only one letter left.
We should also make another baseline where the worst-case win length is bounded by simply using the clues to output all the words in the dictionary in order rather than conveying any semantic information. For example, if the total length of the dictionary is one million characters and the clue length limit is one hundred characters, this baseline wins in no more than ten thousand turns. (Should this replace the other baseline as the mechanic that scores the game after the turn limit is reached?)

---

## 20. Assistant — Design progress message

Earning the last letter has another consequence for candidate filtering: if a contact reveals `art` and the game continues, `art` is ruled out as the target, but it can remain available as an unspoken contact word. I’m adding that distinction and removing the extra END-symbol step I had introduced.

For scoring, the strongest straightforward reference is a script that repeatedly packs a clue plus two guesses from a fresh random ordering of the remaining candidates. Its expected completion time can be computed or reproducibly estimated from word lengths, without using a model.

---

## 21. User

"Earning the last letter has another consequence for candidate filtering: if a contact reveals `art` and the game continues, `art` is ruled out as the target, but it can remain available as an unspoken contact word." No it can't, you can only earn a letter by making contact on a legal dictionary word that hasn't appeared yet. If it had appeared and was the right answer, the game would have ended; the fact that the game hasn't ended necessarily entails that it's not the right answer and not eligible to make contact on.

---

## 22. Assistant — Design progress message

Understood. Once the revealed prefix is itself a dictionary word—such as `art`—that word has appeared and is unavailable for contact. If the game continues, it is also ruled out as the target. My earlier treatment of the displayed prefix as exempt was wrong; I’ll correct both candidate lists and the examples.

---

## 23. Assistant

Correct. **Once `art` has appeared, it is unavailable both as a target candidate and as a future contact word.** My example incorrectly exempted the displayed prefix from the appeared-word rule.

The distinction is now:

- **Privately committed and never revealed:** the word has not been tested or used up, provided it has not appeared elsewhere.
- **Publicly appeared:** if it is the target, the game ends; otherwise it is unavailable for future contact.
- **Final letter earned through contact:** the game ends immediately, without an additional guess or END step.

I’ve corrected the specification and checklist to **v0.4**:

- [CONTACT_BENCHMARK_SPEC.md](CONTACT_BENCHMARK_SPEC.md)
- [CONTACT_PROJECT_CHECKLIST.md](CONTACT_PROJECT_CHECKLIST.md)

On your earlier baseline question: **yes, dictionary enumeration through clues should be included, and I recommend making a combined clue-plus-two-guesses enumerator the fallback after the turn limit.**

### 1. Keep three enumeration baselines

These measure progressively more of the legal guessing capacity:

| Baseline | Procedure | Purpose |
|---|---|---|
| **First/last guessing** | Guesser 1 chooses the first candidate, Guesser 2 the last; always reveal when permitted. | Simple two-guess floor, with worst case $\lceil n/2\rceil$. |
| **Clue-only enumeration** | Fill each clue with consecutive whole dictionary words, within the character limit. | Your proposed demonstration that literal word lists can replace semantic clues. |
| **Combined enumeration** | Fill the clue with candidate words and use the two guesses for additional candidates. | Stronger reference using all available guessing channels; recommended fallback. |

For the combined baseline, a useful packing rule is to **put the two longest words in the selected batch into the guess slots**, and list the remaining words in the clue. That reserves the character budget for the words that consume less space.

The two guessers always reveal when given the cancellation option. A defender cannot prevent those selected words from being tested: blocking one publicly says it, and leaving it unblocked lets the guesser reveal it.

This also means removing the separate four-word mention cap I had proposed earlier. With a character-only clue limit, the reference should use whatever number of complete words actually fits.

### 2. Your character-count argument is right in spirit, with a useful distinction

For **clue-only** enumeration, dividing the dictionary’s total character count by the clue limit is not generally an upper bound. Whole words cannot be split across clues, and separators consume space.

For example, the string:

> `cat dog pig`

contains 11 characters including spaces. With a six-character clue limit, no pair fits, so clue-only enumeration needs three turns—not $\lceil 11/6\rceil=2$.

However, **the combined baseline can recover the kind of upper bound you proposed**, because it has two additional word slots outside the clue budget.

Let:

- $n$ be the number of remaining candidates;
- $C$ be the clue character limit;
- $D$ be the total length of the candidates written with one space between consecutive words.

For the specified greedy combined policy, the worst-case completion time satisfies:

$$
T_{\max}
\le
\min\left(
\left\lceil\frac n2\right\rceil,\,
\left\lceil\frac{D+1}{C+1}\right\rceil
\right).
$$

In particular,

$$
T_{\max}\le \left\lceil\frac DC\right\rceil.
$$

Thus, with **one million characters including separators** and a **100-character clue limit**, the combined policy is guaranteed to finish within **9,901 turns**, and therefore within your proposed 10,000-turn bound.

The distinction is that the two extra guesses compensate for the space wasted at word boundaries. If the million-character count includes only letters, separator overhead must be added.

The specification includes the packing rule and proof, rather than treating dictionary size divided by clue length as an approximation that always holds.

### 3. Use the combined policy for the fallback, with randomized word ordering

I would replace the earlier count-only fallback with the expected completion time of this explicit policy:

1. Take the remaining legal target candidates.
2. Choose a fresh uniformly random ordering.
3. Take the longest initial segment that fits into one clue plus two guess slots.
4. Put its two longest words in the guess slots and list the rest in the clue.
5. Test that batch, remove it if unsuccessful, and repeat with a fresh ordering.

Use an empty defender blocklist for this reference. The reference does not attempt ordinary contacts, so additional defender blocks could only disclose more candidates or themselves say the target.

Randomizing the ordering avoids giving alphabetical position a special role in the score. Fresh randomization on each reference turn also makes the fallback the same continuation policy as the reference used from the beginning.

#### The completion-cost definition remains simple

Write $R_C(S,s)$ for the reference policy’s expected completion time when the remaining candidate set is $S$, the target is $s$, and the clue limit is $C$.

Then:

$$
\text{effective completion time}
=
\begin{cases}
t, & \text{if the model team wins on turn }t,\\[4pt]
L+R_C(S_L,s), & \text{if it remains unresolved after turn }L.
\end{cases}
$$

The initial reference cost is:

$$
B=R_C(S_0,s).
$$

The aggregate speedup remains:

$$
\text{speedup}
=
\frac{\sum B}{\sum \text{effective completion time}}.
$$

The candidate sets exclude every appeared word and respect the current prefix. A concealed, canceled commitment does not remove a candidate merely because the referee recorded it.

### 4. Variable word lengths mean the fallback cannot generally depend only on $n$

Two sets with the same number of candidates can require different enumeration effort if one consists of short words and the other of long words.

For equal-length words, there is still a simple exact formula. If every word has length $\ell$, a turn can test:

$$
b=2+\left\lfloor\frac{C+1}{\ell+1}\right\rfloor
$$

words: two through the guess slots and the rest through the clue. The expected completion time is then:

$$
F_b(n)=\frac1n\sum_{r=1}^n\left\lceil\frac rb\right\rceil.
$$

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

### 5. What this makes the benchmark measure

The stronger reference asks a more useful question:

> **How much does the model improve on a straightforward script that uses the game’s full capacity to enumerate candidates?**

The first/last and clue-only baselines should remain visible, because they explain how much of an apparent improvement comes simply from using more guessing channels.

A gain over the combined reference could come from effective contacts, better target inference, or a better enumeration strategy. It would not, by itself, prove semantic cooperation. That is why the checklist retains comparisons between contact-enabled play, nonsemantic enumeration, and informed guessing.

The revised documents now include the corrected appeared-word rules, immediate final-letter victory, all three baseline families, the recommended character-aware fallback, exact special cases, and numerical-validation requirements.
