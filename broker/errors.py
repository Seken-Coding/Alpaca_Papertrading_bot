"""Helpers for cleaning up broker exception messages for logging."""

import re


def clean_broker_error(exc: Exception) -> str:
    """Return a concise, log-friendly message for a broker exception.

    For alpaca-py APIError instances, extracts the HTTP status code and
    produces a short description instead of dumping raw HTML.
    For auth errors (401/403), includes a hint about credentials.
    For all other exceptions, returns str(exc) unchanged.
    """
    # Try multiple locations where the status code may live:
    # - alpaca-py APIError stores it as exc.status_code
    # - requests HTTPError stores it as exc.response.status_code
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status_code = getattr(resp, "status_code", None)

    raw = str(exc)

    # Even without a status code, try to detect auth errors from HTML body
    if status_code is None:
        if "<html" in raw.lower():
            title_match = re.search(r"<title>(.*?)</title>", raw, re.IGNORECASE)
            # Detect auth-related HTTP errors from the HTML title
            if title_match:
                title = title_match.group(1)
                code_match = re.search(r"(\d{3})", title)
                if code_match:
                    status_code = int(code_match.group(1))
            if status_code is None:
                return f"API error: {title_match.group(1) if title_match else 'unknown HTML error'}"
        else:
            return raw

    # Auth errors get a specific actionable message
    if status_code in (401, 403):
        return (
            f"Authentication failed (HTTP {status_code}) "
            "— check ALPACA_API_KEY and ALPACA_SECRET_KEY"
        )

    # Other API errors: extract a short message, stripping any HTML
    message = getattr(exc, "message", None)
    if message:
        return f"API error (HTTP {status_code}): {message}"

    # Fallback: use str(exc) but strip HTML tags if present
    if "<html" in raw.lower():
        title_match = re.search(r"<title>(.*?)</title>", raw, re.IGNORECASE)
        if title_match:
            return f"API error (HTTP {status_code}): {title_match.group(1)}"
        return f"API error (HTTP {status_code})"

    return f"API error (HTTP {status_code}): {raw}"
