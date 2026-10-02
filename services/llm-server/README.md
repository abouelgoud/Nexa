# LLM server (vLLM + Qwen3)

The platform talks to any **OpenAI-compatible** chat-completions server through
`nexa.providers.llm.OpenAICompatibleLLM`. Locally that is [vLLM](https://docs.vllm.ai) serving Qwen3.

```bash
docker compose --profile gpu up llm        # uses the `llm` service in docker-compose.yml
# or directly on a GPU host:
./serve.sh Qwen/Qwen3-8B
```

Key flags (see `serve.sh`):

| Flag | Why |
|---|---|
| `--enable-auto-tool-choice --tool-call-parser hermes` | Qwen3 emits Hermes-style tool calls; vLLM converts them to OpenAI `tool_calls`. |
| `--max-model-len 8192` | Voice turns are short; a smaller context lowers memory and latency. |
| `chat_template_kwargs.enable_thinking=false` (sent per request by the API) | Disables Qwen3 "thinking" for low latency. Any `<think>` output is stripped and never shown or stored. |

Model sizing guide: `Qwen/Qwen3-8B` (~16 GB VRAM, bf16) is a good default; `Qwen/Qwen3-4B` for
smaller GPUs; `Qwen/Qwen3-14B`/`32B` (or AWQ quantized variants) for better Arabic reasoning.

Without a GPU use the `cpu-llm` profile (Ollama, `qwen3:8b`) - much slower, fine for trying agent mode.
Agents in **workflow mode** (the Doctor template default) do not need an LLM at all.

Switching to a cloud provider later: set `LLM_PROVIDER=cloud`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`
(any OpenAI-compatible endpoint), or add a new `LLMProvider` implementation in `apps/api/nexa/providers/llm/`.
