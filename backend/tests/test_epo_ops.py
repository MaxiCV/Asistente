"""Respuestas sintéticas OPS: no representan evidencia del corpus real."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from app.contracts import PatentFetchConfig
from app.core.config import Settings
from app.core.files import sha256_file
from app.ingestion.epo_ops import FetchFailure, fetch_patents, parse_page


def page(numbers=(100,), total=None, abstract=True, kind="A1"):
    entries = []
    for number in numbers:
        summary = (
            ('<abstract lang="en"><p>First paragraph.</p><p>Second paragraph.</p></abstract>')
            if abstract
            else ""
        )
        entries.append(f"""<exchange-document><bibliographic-data>
        <publication-reference><document-id document-id-type="docdb">
        <country>EP</country><doc-number>{number}</doc-number><kind>{kind}</kind>
        <date>20261110</date></document-id></publication-reference>
        <invention-title lang="de">Test DE</invention-title>
        <invention-title lang="en">Synthetic title</invention-title>
        </bibliographic-data>{summary}</exchange-document>""")
    total = len(numbers) if total is None else total
    return (
        f'<ops:world-patent-data xmlns:ops="http://ops.epo.org" '
        f'xmlns="http://www.epo.org/exchange"><ops:biblio-search '
        f'total-result-count="{total}"><ops:search-result><exchange-documents>'
        + "".join(entries)
        + "</exchange-documents></ops:search-result></ops:biblio-search>"
        "</ops:world-patent-data>"
    ).encode()


@pytest.fixture
def capture(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        ASISTENTE_DATA_DIR=tmp_path,
        epo_ops_consumer_key="fixture-key",
        epo_ops_consumer_secret="fixture-secret",
    )
    real_client = httpx.Client
    sleeps, requests = [], []
    monkeypatch.setattr("app.ingestion.epo_ops.time.sleep", sleeps.append)

    def run(handler, **overrides):
        def handle(request):
            requests.append(request)
            if request.method == "POST":
                assert request.content == b"grant_type=client_credentials"
                assert request.headers["Authorization"].startswith("Basic ")
                return httpx.Response(
                    200, json={"access_token": "fixture-token", "expires_in": "1200"}
                )
            assert request.headers["Authorization"] == "Bearer fixture-token"
            return handler(request)

        monkeypatch.setattr(
            "app.ingestion.epo_ops.httpx.Client",
            lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
        )
        return fetch_patents(
            settings, PatentFetchConfig(query='ta="fall detection"', **overrides), "fixture"
        )

    return run, sleeps, requests


def test_capture_pages_dedup_hashes_secrets_and_no_overwrite(capture, tmp_path):
    run, sleeps, requests = capture

    def handle(request):
        assert request.url.params["q"] == 'ta="fall detection"'
        content = (
            page((100, 101), total=9)
            if request.url.params["Range"] == "1-2"
            else page((100,), total=9)
        )
        return httpx.Response(200, content=content)

    result = run(handle, max_records=3, page_size=2)
    assert result["status"] == "complete"
    assert result["record_count"] == 2
    assert result["duplicate_observations"] == 1
    assert result["stop_reason"] == "record_limit"
    assert len(requests) == 3 and sleeps == [6, 6]
    target = tmp_path / "patents/snapshots/fixture"
    for name, digest in result["files"].items():
        assert sha256_file(target / name) == digest
    for file in target.iterdir():
        text = file.read_text("utf-8")
        assert all(
            secret not in text for secret in ("fixture-key", "fixture-secret", "fixture-token")
        )
    before = (target / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        run(handle)
    assert (target / "manifest.json").read_bytes() == before


def test_normalization_preserves_kind_date_content_and_language():
    now = datetime.now(UTC)
    total, docs = parse_page(page(kind="B1"), "fixture", now)
    doc = docs[0]
    assert total == 1 and doc.publication_id == "EP.100.B1"
    assert doc.publication_date.isoformat() == "2026-11-10"
    assert doc.title == "Synthetic title" and doc.language == "en"
    assert doc.abstract == "First paragraph.\n\nSecond paragraph."
    assert doc.abstract_language == "en" and doc.content_level == "abstract"
    assert doc.retrieved_at == now and doc.source == "epo_ops"
    assert doc.document_type == "patent"
    assert parse_page(page(abstract=False), "fixture", now)[1][0].content_level == "metadata"


@pytest.mark.parametrize(
    "content",
    [
        b"<broken",
        b"<html/>",
        b'<!DOCTYPE a [<!ENTITY x "secret">]><a>&x;</a>',
        page().replace(b"20261110", b"20260230"),
        page().replace(b"<kind>A1</kind>", b"<kind></kind>"),
        page().replace(b"docdb", b"epodoc"),
    ],
)
def test_invalid_xml_is_controlled(content):
    with pytest.raises(FetchFailure, match="^OPS_INVALID_RESPONSE$"):
        parse_page(content, "fixture", datetime.now(UTC))


@pytest.mark.parametrize(
    "status,headers,error",
    [
        (403, {}, "OPS_QUOTA_OR_ACCESS_DENIED"),
        (200, {"X-Throttling-Control": "busy (search=black:0)"}, "OPS_QUOTA_OR_ACCESS_DENIED"),
        (429, {"Retry-After": "120"}, "RETRY_AFTER_EXCEEDS_BUDGET"),
        (400, {}, "OPS_HTTP_400"),
        (404, {}, "OPS_HTTP_404"),
        (302, {"Location": "https://example.org"}, "OPS_HTTP_302"),
    ],
)
def test_failures_leave_incomplete_snapshot(capture, tmp_path, status, headers, error):
    run, _, requests = capture
    with pytest.raises(FetchFailure, match=error):
        run(lambda _: httpx.Response(status, headers=headers, text="private-provider-body"))
    manifest = json.loads((tmp_path / "patents/snapshots/fixture/manifest.json").read_text())
    assert manifest["status"] == "incomplete" and manifest["error_code"] == error
    assert "private-provider-body" not in json.dumps(manifest)
    assert len(requests) == 2


def test_retry_after_then_success(capture):
    run, sleeps, requests = capture

    def handle(_):
        return (
            httpx.Response(429, headers={"Retry-After": "8"})
            if len(requests) == 2
            else httpx.Response(200, content=page())
        )

    assert run(handle)["status"] == "complete"
    assert 8 in sleeps


def test_token_refreshed_once(capture):
    run, _, requests = capture

    def handle(_):
        return httpx.Response(401) if len(requests) == 2 else httpx.Response(200, content=page())

    assert run(handle)["status"] == "complete"
    assert [r.method for r in requests] == ["POST", "GET", "POST", "GET"]


def test_repeated_unauthorized_stops(capture):
    run, _, requests = capture
    with pytest.raises(FetchFailure, match="OPS_HTTP_401"):
        run(lambda _: httpx.Response(401))
    assert len(requests) == 4


def test_transport_retry_exhaustion(capture):
    run, _, requests = capture

    def handle(request):
        raise httpx.ReadTimeout("private-provider-body", request=request)

    with pytest.raises(FetchFailure, match="^OPS_TRANSPORT_ERROR$"):
        run(handle)
    assert len(requests) == 4


def test_request_budget(capture):
    run, _, requests = capture
    with pytest.raises(FetchFailure, match="OPS_REQUEST_LIMIT"):
        run(lambda _: httpx.Response(200, content=page()), max_requests=1)
    assert len(requests) == 1


def test_empty_result_and_short_page(capture):
    run, _, _ = capture
    assert run(lambda _: httpx.Response(200, content=page(())))["record_count"] == 0


def test_truncated_page_is_not_success(capture):
    run, _, _ = capture
    with pytest.raises(FetchFailure, match="OPS_UNEXPECTED_PAGE_SIZE"):
        run(lambda _: httpx.Response(200, content=page(total=20)))


def test_dynamic_throttling(capture):
    run, sleeps, _ = capture

    def handle(request):
        number = 100 if request.url.params["Range"] == "1-1" else 101
        return httpx.Response(
            200,
            content=page((number,), total=2),
            headers={"X-Throttling-Control": "busy (search=red:2)"},
        )

    assert run(handle, page_size=1)["record_count"] == 2
    assert sleeps == [6, 30]


def test_missing_credentials_has_no_side_effects(tmp_path, monkeypatch):
    monkeypatch.delenv("EPO_OPS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_CONSUMER_SECRET", raising=False)
    with pytest.raises(FetchFailure, match="OPS_CREDENTIALS_MISSING"):
        fetch_patents(
            Settings(_env_file=None, ASISTENTE_DATA_DIR=tmp_path),
            PatentFetchConfig(query="test"),
            "fixture",
        )
    assert not list(tmp_path.iterdir())
