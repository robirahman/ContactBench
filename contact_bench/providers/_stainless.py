"""Exception mapping shared by the OpenAI and Anthropic (Stainless-generated) SDKs."""

from __future__ import annotations

from types import ModuleType

from ._util import get, retry_after_from_headers
from .base import InfrastructureError, sanitize


def _body_code(e: BaseException) -> str:
    body = getattr(e, "body", None)
    err = get(body, "error", body)
    code = get(err, "code") or get(err, "type") or ""
    return str(code)


def map_stainless_error(e: BaseException, sdk: ModuleType, secrets: tuple[str, ...]) -> InfrastructureError:
    msg = sanitize(f"{type(e).__name__}: {e}", secrets)
    response = getattr(e, "response", None)
    retry_after = retry_after_from_headers(getattr(response, "headers", None))
    status = getattr(e, "status_code", None)
    code = _body_code(e)

    def mk(category: str, *, retryable: bool = False, fatal: bool = False, billed: bool = False):
        return InfrastructureError(
            msg, category=category, retryable=retryable, fatal=fatal, retry_after=retry_after, possibly_billed=billed
        )

    if isinstance(e, sdk.APITimeoutError):
        # The provider may have generated (and billed) a response.
        return mk("timeout", retryable=True, billed=True)
    if isinstance(e, sdk.APIConnectionError):
        return mk("transient", retryable=True)
    if isinstance(e, sdk.RateLimitError):
        low = (msg + " " + code).lower()
        # A 429 can also mean the prepaid balance is gone ("You have no credits
        # remaining"); retrying cannot help, so halt the credential.
        if any(k in low for k in ("insufficient_quota", "billing", "no credits", "credits remaining",
                                  "add credits", "credit balance")):
            return mk("quota_exhausted", fatal=True)
        return mk("rate_limit", retryable=True)
    if isinstance(e, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
        return mk("auth", fatal=True)
    if isinstance(e, sdk.NotFoundError):
        return mk("invalid_model", fatal=True)
    if isinstance(e, (sdk.BadRequestError, getattr(sdk, "UnprocessableEntityError", sdk.BadRequestError))):
        low = (msg + code).lower()
        if "unsupported" in low or "unknown parameter" in low or "not supported" in low or "extra inputs" in low:
            return mk("unsupported_parameter", fatal=True)
        if "credit" in low or "quota" in low or "billing" in low:
            return mk("quota_exhausted", fatal=True)
        return mk("bad_request", fatal=True)
    if isinstance(status, int) and status == 402:
        # Payment required / credits depleted: a billing failure of the shared key.
        return mk("quota_exhausted", fatal=True)
    if isinstance(e, sdk.InternalServerError) or (isinstance(status, int) and status >= 500):
        return mk("server", retryable=True)
    if isinstance(status, int) and status in (408, 409):
        return mk("transient", retryable=True)
    if isinstance(e, sdk.APIStatusError):
        return mk("unknown", fatal=True)
    return mk("unknown", fatal=True)
