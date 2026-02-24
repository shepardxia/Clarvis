"""Vendored Anthropic/Claude backend for memU.

Based on memU PR #214 (NevaMind-AI/memU). Patches memU's LLM dispatch
to support ``provider="claude"`` and ``client_backend="claude_sdk"``.

Call ``apply_patch()`` once before creating a ``MemoryService``.
"""

from clarvis.vendor.memu_claude.backend import ClaudeLLMBackend
from clarvis.vendor.memu_claude.sdk_client import ClaudeSDKClient

_PATCHED = False


def apply_patch() -> None:
    """Monkey-patch memU to support Claude as an LLM provider."""
    global _PATCHED
    if _PATCHED:
        return

    import memu.llm.http_client as http_mod
    from memu.app.service import MemoryService

    # 1. Register Claude in the HTTP backend registry
    http_mod.LLM_BACKENDS[ClaudeLLMBackend.name] = ClaudeLLMBackend

    # 2. Patch _headers() to use x-api-key for Claude
    _orig_headers = http_mod.HTTPLLMClient._headers

    def _patched_headers(self: http_mod.HTTPLLMClient) -> dict[str, str]:
        if self.provider == "claude":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        return _orig_headers(self)

    http_mod.HTTPLLMClient._headers = _patched_headers

    # 3. Patch _load_embedding_backend() — Claude has no embeddings, fall back to OpenAI
    _orig_load_embed = http_mod.HTTPLLMClient._load_embedding_backend

    def _patched_load_embed(self: http_mod.HTTPLLMClient, provider: str) -> http_mod._EmbeddingBackend:
        if provider == "claude":
            return http_mod._OpenAIEmbeddingBackend()
        return _orig_load_embed(self, provider)

    http_mod.HTTPLLMClient._load_embedding_backend = _patched_load_embed

    # 4. Patch _init_llm_client() to handle client_backend="claude_sdk"
    _orig_init = MemoryService._init_llm_client

    def _patched_init(self: MemoryService, config=None):
        from memu.app.settings import LLMConfig

        cfg: LLMConfig = config or self.llm_config
        if cfg.client_backend == "claude_sdk":
            return ClaudeSDKClient(
                api_key=cfg.api_key,
                chat_model=cfg.chat_model,
                base_url=cfg.base_url if cfg.base_url != "https://api.openai.com/v1" else None,
                embed_model=cfg.embed_model,
            )
        return _orig_init(self, config)

    MemoryService._init_llm_client = _patched_init

    _PATCHED = True


__all__ = ["ClaudeLLMBackend", "ClaudeSDKClient", "apply_patch"]
