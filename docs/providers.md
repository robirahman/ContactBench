# Provider adapters

All adapters implement `contact_bench.providers.base.ProviderAdapter`. Each one sends one stateless
request per decision. The system prompt holds the rules. The single user message holds the seat's
filtered observation and its permitted history. An adapter never repairs, substitutes or semantically
retries an answer. The engine validates every output.

| Provider | `api_family` | Class | SDK call | Structured output |
|---|---|---|---|---|
| OpenAI | `responses` | `OpenAIResponsesAdapter` | `AsyncOpenAI(max_retries=0).responses.create` | `text.format = {type: json_schema, name, schema, strict: true}` |
| Anthropic | `messages` | `AnthropicMessagesAdapter` | `AsyncAnthropic(max_retries=0).messages.create` | `output_config.format = {type: json_schema, schema}` |
| Google | `interactions` (default) | `GeminiInteractionsAdapter` | `Client(...).aio.interactions.create(automatic_continuation=False)` | `response_format = {type: text, mime_type: application/json, schema}` |
| Google | `generate_content` (compatibility) | `GeminiGenerateContentAdapter` | `Client(...).aio.models.generate_content` | `config.response_mime_type=application/json`, `config.response_json_schema` |
| Offline | `fake` | `FakeAdapter` | none | legal first/last policy plus canned failure fixtures |

`registry.make_adapter(model_config)` selects the class. Constructing an adapter or running offline
`preflight()` never reads credentials or touches the network. `preflight(require_credentials=True)`
or `check_credentials()` checks that the key is present. The client is created lazily on first send.

## Tested SDK versions

Pinned and tested offline with mocked clients (`tests/test_providers.py`):

- `openai==3.52.0`
- `anthropic==2.9.0`
- `google-genai==3.4.0`

`registry.tested_sdk_versions()` reports the installed versions for run manifests.

## Parameters

Requested parameters must be in the adapter's `supported_parameters`; otherwise preflight fails with
an actionable error. Nothing is silently dropped. `AdapterResponse.requested_parameters` and
`effective_parameters` are recorded separately.

- OpenAI: `reasoning`, `temperature`, `top_p`, `service_tier`, `prompt_cache_key`,
  `prompt_cache_retention`, `truncation` (sent verbatim). Model-specific restrictions, e.g.
  reasoning models rejecting `temperature`, surface as provider 400 errors (fatal, `bad_request`).
- Anthropic: `thinking`, `effort` (sent as `output_config.effort`), `service_tier`, `speed`,
  `inference_geo`. `temperature`/`top_p`/`top_k` are **unsupported**. The installed SDK's
  `messages.create` has no such arguments, and the spec notes that API version 2026-10-21 rejects them.
- Gemini Interactions: `thinking_level`, `thinking_summaries`, `temperature`, `top_p`, `seed`
  (inside `generation_config`), and `service_tier` (top level).
- Gemini generateContent: `thinking_config`, `temperature`, `top_p`, `seed` (inside `config`).

`max_output_tokens` must be set explicitly per model. It must also be large enough for a full
admitted blocklist for the selected lexicon; the runner checks this.

## Storage and state

- OpenAI: `store=False`; no `previous_response_id` or conversations.
- Anthropic: Messages is stateless; history is caller-supplied.
- Gemini Interactions: `store=False`; no `previous_interaction_id`. `automatic_continuation=False`,
  because the SDK would otherwise issue extra generation hops. A `requires_continuation` status is
  recorded as `incomplete`.

Turning off a storage feature does not mean the provider keeps nothing.

## Retries

`ProviderAdapter.decide` owns all retries. It allows at most `max_attempts` attempts (default 3) with
the same request. It honors `Retry-After` when present and otherwise uses exponential backoff with
jitter, under an overall deadline. Fatal errors (auth, invalid model, unsupported or bad request,
exhausted quota) are never retried. The first complete response is used. SDK-level retries are
disabled so the two retry layers cannot multiply:

- OpenAI/Anthropic: `max_retries=0`.
- Google: `HttpOptions(retry_options=HttpRetryOptions(attempts=1))`. This is required: with
  `retry_options` unset, the Interactions client falls back to 5 attempts (4 retries); generateContent
  falls back to none. A test asserts `max_retries == 0` on the Interactions client.

Timeouts are marked `possibly_billed=True`, because the provider may already have generated the
response.

## Error mapping

| Condition | Category | Retry |
|---|---|---|
| 429 rate limit | `rate_limit` | yes (Retry-After honored) |
| OpenAI 429 `insufficient_quota` | `quota_exhausted` | fatal |
| timeout | `timeout` | yes, possibly billed |
| connection error, 408/409 | `transient` | yes |
| 5xx including Anthropic 529 overloaded | `server` | yes |
| Gemini interaction `failed`/`cancelled` | `server` | yes, possibly billed |
| 401/403 | `auth` | fatal |
| 404 | `invalid_model` | fatal |
| 400 mentioning an unsupported/unknown field | `unsupported_parameter` | fatal |
| other 400 | `bad_request` | fatal |

Gemini 429 `RESOURCE_EXHAUSTED` cannot be told apart from an exhausted project quota by status alone.
It is retried within the bounded policy. Gemini quotas can apply at project scope.

Error messages are passed through `sanitize()`, which removes the configured key value, `sk-…`,
`AIza…`, bearer tokens and `api_key=`/`Authorization:` values before logging.

## Model behavior versus infrastructure

Refusals and truncations are model behavior, not infrastructure errors. They come back as responses
with `refusal=True` / `incomplete=True`, and the engine applies the declared invalid-output penalty.

- OpenAI: `refusal` content item → refusal. `status == "incomplete"` → incomplete, and
  `finish_reason = incomplete_details.reason`.
- Anthropic: `stop_reason == "refusal"` → refusal. `max_tokens`, `model_context_window_exceeded` and
  `pause_turn` → incomplete. Thinking blocks are ignored; text blocks are concatenated.
- Gemini Interactions: `incomplete`, `budget_exceeded` or `requires_continuation` → incomplete. The
  API has no explicit refusal flag, so a refusal appears as invalid or empty output.
- Gemini generateContent: `prompt_feedback.block_reason` or a safety-type `finish_reason` → refusal.
  `MAX_TOKENS` → incomplete. Thought parts are excluded from the text.

## Usage accounting

`NormalizedUsage` fields are nullable: unknown is `None`, never zero. `raw_usage` keeps the provider's
original object. `reasoning_included_in_output` records the convention, and
`billable_output_tokens()` uses it so reasoning tokens are never counted twice.

| Provider | input | output | reasoning | convention |
|---|---|---|---|---|
| OpenAI Responses | `input_tokens` (cached: `input_tokens_details.cached_tokens`) | `output_tokens` | `output_tokens_details.reasoning_tokens` | subset of output (`True`) |
| Anthropic Messages | `input_tokens` (+ `cache_read_input_tokens`, `cache_creation_input_tokens`) | `output_tokens` | `output_tokens_details.thinking_tokens` if present | treated as subset of output (`True`); `None` when absent |
| Gemini Interactions | `total_input_tokens` (cached: `total_cached_tokens`) | `total_output_tokens` | `total_thought_tokens` | separate (`False`) |
| Gemini generateContent | `prompt_token_count` | `candidates_token_count` | `thoughts_token_count` | separate (`False`) |

Anthropic does not report a total. The adapter computes one as input + output + cache read + cache
write.

## Official documentation (checked 16 November 2026; recheck before live runs)

- OpenAI Structured outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Responses reference: https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI Counting tokens: https://developers.openai.com/api/docs/guides/token-counting
- OpenAI Rate limits: https://developers.openai.com/api/docs/guides/rate-limits
- Anthropic Messages: https://platform.claude.com/docs/en/build-with-claude/working-with-messages
- Anthropic Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Anthropic Thinking: https://platform.claude.com/docs/en/build-with-claude/thinking
- Anthropic Extended thinking: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Anthropic Rate limits: https://platform.claude.com/docs/en/api/rate-limits
- Google Migrating to Interactions: https://aistudio.google.com/docs/migrate-to-interactions
- Google Structured outputs: https://aistudio.google.com/docs/structured-output
- Google Thinking: https://aistudio.google.com/docs/thinking
- Google Rate limits: https://aistudio.google.com/docs/rate-limits

## Known gaps and uncertainties

- **No live call has been made.** Request shapes were taken from the installed SDK sources and
  checked against mocked clients only. The researcher must run the opt-in smoke command for each
  provider before relying on an adapter.
- Anthropic `thinking_tokens`: the docs were not consulted live. The adapter assumes these tokens
  are included in `output_tokens`, which is how thinking is billed. Verify this on a smoke run.
- Gemini Interactions JSON-schema support covers only a subset of JSON Schema, and nullable unions
  such as `["string","null"]` may need checking against the live API. The engine validates every
  output locally either way.
- Gemini Interactions responses expose no HTTP request ID through the SDK object, so `request_id`
  is `None`. OpenAI and Anthropic use the SDK's `_request_id`.
- Error classification matches on message substrings for unsupported parameters and quota. A
  misclassified 400 still fails safely as a fatal `bad_request`.
