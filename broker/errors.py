"""Helpers for cleaning up broker exception messages for logging."""

import re


def _strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace, returning plain text."""
    if "<html" not in text.lower():
        return text
    # Try to extract just the <title> for a concise message
    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
    if title_match:
        return title_match.group(1).strip()
    # Fallback: remove all tags and collapse whitespace
    stripped = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", stripped).strip()


def _extract_status_code(exc: Exception) -> int | None:
    """Try to find an HTTP status code from the exception."""
    # alpaca-py APIError: exc.status_code
    code = getattr(exc, "status_code", None)
    if code is not None:
        try:
            return int(code)
        except (ValueError, TypeError):
            pass

    # requests HTTPError: exc.response.status_code
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (ValueError, TypeError):
                pass

    # Last resort: extract from HTML title like "401 Authorization Required"
    raw = str(exc)
    title_match = re.search(r"<title>(\d{3})\b[^<]*</title>", raw, re.IGNORECASE)
    if title_match:
        return int(title_match.group(1))

    return None


def clean_broker_error(exc: Exception) -> str:
    """Return a concise, log-friendly message for a broker exception.

    Never returns raw HTML — always strips it to a readable summary.
    For auth errors (401/403), includes a hint about checking credentials.
    """
    status_code = _extract_status_code(exc)
    raw = str(exc)

    # Auth errors get a specific actionable message
    if status_code in (401, 403):
        return (
            f"Authentication failed (HTTP {status_code}) "
            "— check ALPACA_API_KEY and ALPACA_SECRET_KEY"
        )

    # For other status codes, build a clean message
    if status_code is not None:
        message = getattr(exc, "message", None)
        if message:
            return f"API error (HTTP {status_code}): {_strip_html(message)}"
        clean = _strip_html(raw)
        if clean:
            return f"API error (HTTP {status_code}): {clean}"
        return f"API error (HTTP {status_code})"

    # No status code found — return str(exc) but strip any HTML
    return _strip_html(raw) or raw
