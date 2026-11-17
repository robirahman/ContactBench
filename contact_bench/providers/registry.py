"""Adapter factory and SDK version inventory."""

from __future__ import annotations

from importlib import metadata

from ..config import ModelConfig
from .base import AdapterConfigError, CredentialSource, ProviderAdapter, RetryPolicy

SDK_PACKAGES = ("openai", "anthropic", "google-genai")


def make_adapter(
    model_config: ModelConfig,
    *,
    credentials: CredentialSource | None = None,
    retry: RetryPolicy | None = None,
    **kwargs,
) -> ProviderAdapter:
    """Construct the adapter for a model.  Never reads credentials or touches the network."""
    p = model_config.provider
    common = dict(credentials=credentials, retry=retry, **kwargs)
    if p == "fake":
        from .fake import FakeAdapter

        return FakeAdapter(model_config, **common)
    if p == "openai":
        from .openai_adapter import OpenAIResponsesAdapter

        return OpenAIResponsesAdapter(model_config, **common)
    if p == "anthropic":
        from .anthropic_adapter import AnthropicMessagesAdapter

        return AnthropicMessagesAdapter(model_config, **common)
    if p == "google":
        from .google_adapter import GeminiGenerateContentAdapter, GeminiInteractionsAdapter

        if model_config.effective_api_family == "generate_content":
            return GeminiGenerateContentAdapter(model_config, **common)
        return GeminiInteractionsAdapter(model_config, **common)
    raise AdapterConfigError(f"provider {p!r} has no model adapter (scripted policies run locally)")


def tested_sdk_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for pkg in SDK_PACKAGES:
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out
