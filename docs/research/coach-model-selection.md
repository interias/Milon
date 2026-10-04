# Coach model selection

Checked on 2026-10-04 against official model documentation and OpenRouter's current catalogue. This comparison covers the existing Chat Completions loop, German answers of roughly 120 words, and Milon's metric tools. It does not establish coaching quality through a benchmark.

**Recommendation: `openai/gpt-6-luna` with reasoning disabled for the existing tool loop.** OpenAI positions Luna for focused, efficient work. Its documented Chat Completions function calling requires `reasoning_effort: "none"`; reasoning with tools requires the Responses API. This is an implementation constraint, not a preference for lower answer quality. [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna), [migration guide](https://developers.openai.com/api/docs/guides/latest-model#migration-quickstart)

| Candidate | Standard input/output per million tokens | Fit for this integration |
| --- | --- | --- |
| [GPT-6 Luna](https://openrouter.ai/openai/gpt-6-luna) | $0.10 / $0.50 | Lowest listed rates of these candidates; supports tools and a low verbosity setting. Set `reasoning_effort: "none"` and omit temperature because the current OpenRouter endpoints do not advertise it. |
| [Gemini 3.8 Flash](https://openrouter.ai/google/gemini-3.8-flash) | $0.75 / $3.75 | Current Flash model with tools; supports reasoning. Tool continuations should preserve complete `reasoning_details`; the current client discards those fields. |
| [Claude Sonnet 5.5](https://openrouter.ai/anthropic/claude-sonnet-5.5) | $2.00 / $10.00 | Current Sonnet model with tools and always-active thinking; requires reasoning replay and costs more for this short-answer workload. |

Rates are current catalogue values for standard routing, excluding cache writes, discounts and additional services. The Gemini rate is a current promotional rate. Endpoint-specific availability and parameters can change. [Luna endpoint catalogue](https://openrouter.ai/api/v1/models/openai/gpt-6-luna/endpoints), [reasoning continuation documentation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#preserving-reasoning)

OpenRouter currently shows standard endpoint median latencies of roughly 2.24 seconds for Luna/OpenAI, 1.40 seconds for Gemini/AI Studio and 2.43 seconds for Sonnet/Anthropic. These are provider statistics, not end-to-end timings for Milon's multi-round coach. They do not establish that any model will finish this application request faster. [Luna](https://openrouter.ai/openai/gpt-6-luna), [Gemini](https://openrouter.ai/google/gemini-3.8-flash), [Sonnet](https://openrouter.ai/anthropic/claude-sonnet-5.5)

Claude Haiku 4.5 remains available at $1/$5 per million input/output tokens and supports tools. It is an alternative if a later local comparison demonstrates better German answers; this research found no Milon-specific evidence for that improvement. [Haiku catalogue](https://openrouter.ai/anthropic/claude-haiku-4.5)

The recommendation is an inference from costs, documented capabilities and integration size. Keep the concise prompt and saved chart snapshots independently of the model. A real Milon request on 2026-10-04 returned HTTP 200, used the sleep overview and performance tools, respected the short German answer format and correctly described the returned data limitations. OpenRouter billed $0.00094455 for that request. The private response is saved only under ignored `data/audits/`. A single successful response confirms the integration, not general coaching reliability.

## Image integration

Use the separate `openai/gpt-image-2.5-flare` model for illustrations. OpenRouter documents `POST /api/v1/images`, square `size: "1024x1024"`, `quality: "low"`, base64 image bytes and optional `usage.cost`. The model's current endpoint advertises low quality and square aspect ratio. The implementation validates the actual 1024-square raster result before saving it locally. It sends the explicit illustration subject and Milon's visual style; it does not attach fitness records, reports or progress photos. The paid image API was not called during this implementation. [OpenRouter Image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation), [Flare endpoint capabilities](https://openrouter.ai/api/v1/images/models/openai/gpt-image-2.5-flare/endpoints), [OpenAI image documentation](https://developers.openai.com/api/docs/guides/image-generation)
