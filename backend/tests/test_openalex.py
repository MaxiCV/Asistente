import httpx
import pytest
from app.core.config import Settings
from app.ingestion.openalex import check_openalex


def test_check_uses_auth_header_and_limits_output(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-only-key"
        assert "api_key" not in request.url.params
        if request.url.path == "/works":
            return httpx.Response(200, json={"results": [], "meta": {"next_cursor": "next"}})
        return httpx.Response(
            200,
            json={
                "api_key": "must-not-be-returned",
                "rate_limit": {"daily_remaining_usd": 0.99, "private": "must-not-be-returned"},
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        "app.ingestion.openalex.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    result = check_openalex(Settings(_env_file=None, openalex_api_key="test-only-key"))
    assert result["quota"] == {"daily_remaining_usd": 0.99}
    assert len(requests) == 2
    assert "test-only-key" not in str(result)


def test_missing_key_is_rejected_without_request():
    with pytest.raises(ValueError, match="OPENALEX_API_KEY"):
        check_openalex(Settings(_env_file=None, openalex_api_key=None))


def test_auth_failure_does_not_echo_provider_body(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.ingestion.openalex.httpx.Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    403,
                    json={"message": "secret-provider-body"},
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError, match="HTTP 403") as error:
        check_openalex(Settings(_env_file=None, openalex_api_key="test-only-key"))
    assert "secret-provider-body" not in str(error.value)
