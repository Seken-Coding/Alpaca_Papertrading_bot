"""Tests for broker.errors — clean_broker_error helper."""

from broker.errors import clean_broker_error


class _FakeAPIError(Exception):
    """Mimics alpaca.common.exceptions.APIError for testing."""

    def __init__(self, status_code, message=None, body=""):
        self.status_code = status_code
        self.message = message
        super().__init__(body or message or "")


def test_passthrough_for_regular_exception():
    exc = ValueError("something broke")
    assert clean_broker_error(exc) == "something broke"


def test_401_auth_error():
    exc = _FakeAPIError(401, body="<html><head><title>401 Authorization Required</title></head></html>")
    result = clean_broker_error(exc)
    assert "Authentication failed" in result
    assert "HTTP 401" in result
    assert "ALPACA_API_KEY" in result


def test_403_auth_error():
    exc = _FakeAPIError(403)
    result = clean_broker_error(exc)
    assert "Authentication failed" in result
    assert "HTTP 403" in result


def test_api_error_with_message():
    exc = _FakeAPIError(500, message="Internal Server Error")
    result = clean_broker_error(exc)
    assert result == "API error (HTTP 500): Internal Server Error"


def test_api_error_html_body_extracts_title():
    exc = _FakeAPIError(
        502,
        body="<html><head><title>502 Bad Gateway</title></head><body>...</body></html>",
    )
    result = clean_broker_error(exc)
    assert result == "API error (HTTP 502): 502 Bad Gateway"


def test_api_error_html_body_no_title():
    exc = _FakeAPIError(504, body="<html><body>no title here</body></html>")
    result = clean_broker_error(exc)
    assert result == "API error (HTTP 504)"


def test_api_error_plain_text_body():
    exc = _FakeAPIError(429, body="rate limit exceeded")
    result = clean_broker_error(exc)
    assert result == "API error (HTTP 429): rate limit exceeded"


class _FakeResponse:
    """Mimics a requests.Response for testing."""

    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHTTPError(Exception):
    """Mimics requests.exceptions.HTTPError — status on .response."""

    def __init__(self, status_code, body=""):
        self.response = _FakeResponse(status_code)
        super().__init__(body)


def test_401_from_response_attribute():
    """Exception with status_code on .response (requests-style)."""
    exc = _FakeHTTPError(401, body="<html><head><title>401 Authorization Required</title></head></html>")
    result = clean_broker_error(exc)
    assert "Authentication failed" in result
    assert "HTTP 401" in result
    assert "ALPACA_API_KEY" in result


def test_html_body_without_status_code_attribute():
    """Exception with no status_code attr at all but HTML in str()."""
    html = "<html><head><title>401 Authorization Required</title></head><body></body></html>"
    exc = Exception(html)
    result = clean_broker_error(exc)
    assert "Authentication failed" in result
    assert "HTTP 401" in result
    assert "<html" not in result


def test_html_body_non_auth_without_status_code():
    """Exception with HTML body containing a non-auth error code."""
    html = "<html><head><title>502 Bad Gateway</title></head></html>"
    exc = Exception(html)
    result = clean_broker_error(exc)
    assert "502" in result
    assert "<html" not in result
