import json
from datetime import date

import httpx
import pytest
from app.contracts import FetchConfig, FetchSearch
from app.core.config import Settings
from app.ingestion.openalex import FetchFailure, _retry_delay, fetch_snapshot
from app.ingestion.snapshot import read_snapshot


def work(number):
    return {"id": f"https://openalex.org/W{number}", "title": f"Synthetic test {number}"}


def page(works, cursor=None):
    return httpx.Response(200, json={"results": works, "meta": {"next_cursor": cursor}})


@pytest.fixture
def capture(tmp_path, monkeypatch):
    config = FetchConfig(
        searches=[FetchSearch(query="fall detection", has_abstract=True, max_records=3)],
        per_page=2,
        request_interval_seconds=0,
    )
    settings = Settings(
        _env_file=None, ASISTENTE_DATA_DIR=tmp_path, openalex_api_key="synthetic-secret"
    )
    real_client = httpx.Client
    sleeps = []
    monkeypatch.setattr("app.ingestion.openalex.time.sleep", sleeps.append)

    def run(handler, name="fixture", cfg=None):
        monkeypatch.setattr(
            "app.ingestion.openalex.httpx.Client",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        )
        return fetch_snapshot(settings, cfg or config, name, date(2026, 11, 5))

    return run, config, sleeps


def test_cursor_dedup_provenance_filters_and_snapshot_reuse(capture, tmp_path):
    run, _, _ = capture
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-secret"
        assert "api_key" not in request.url.params
        assert "to_publication_date:2026-11-05" in request.url.params["filter"]
        if len(requests) == 1:
            return page([work(1), work(2)], "second")
        assert request.url.params["cursor"] == "second"
        assert request.url.params["per_page"] == "1"
        return page([work(1)], "third")

    manifest = run(handle)
    assert manifest.status == "complete"
    assert manifest.record_count == 2
    assert manifest.duplicate_observations == 1
    assert len(requests) == 2  # Configured sample complete, not the entire search.
    snapshot = tmp_path / "snapshots/fixture"
    assert len(read_snapshot(snapshot)[1]) == 2
    original = (snapshot / "works.jsonl").read_bytes()
    logs = (snapshot / "requests.jsonl").read_text("utf-8")
    assert "record_limit" in logs and "W1" in logs
    for path in snapshot.iterdir():
        assert "synthetic-secret" not in path.read_text("utf-8")
    with pytest.raises(FileExistsError):
        run(handle)
    assert (snapshot / "works.jsonl").read_bytes() == original


def test_retries_honor_retry_after_and_transport_failures(capture):
    run, _, sleeps = capture
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("must-not-be-logged", request=request)
        if len(attempts) == 2:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return page([work(1)])

    manifest = run(handle)
    assert manifest.request_count == 3
    assert [sleep for sleep in sleeps if sleep] == [1, 4]


@pytest.mark.parametrize("status", [401, 403, 500, 429])
def test_failure_is_incomplete_sanitized_and_preserves_old_snapshot(capture, tmp_path, status):
    run, config, _ = capture
    run(lambda _: page([work(1)]), name="previous")
    previous = tmp_path / "snapshots/previous/manifest.json"
    original = previous.read_bytes()
    with pytest.raises(FetchFailure, match=f"HTTP_{status}"):
        run(lambda _: httpx.Response(status, text="secret-body"), cfg=config)
    snapshot = tmp_path / "snapshots/fixture"
    manifest = json.loads((snapshot / "manifest.json").read_text("utf-8"))
    assert manifest["status"] == "incomplete"
    assert manifest["request_count"] == (1 if status in (401, 403) else 4)
    assert "secret-body" not in str(manifest)
    with pytest.raises(ValueError, match="completo"):
        read_snapshot(snapshot)
    assert previous.read_bytes() == original
    assert all(
        json.loads(p.read_text("utf-8"))["status"] != "running"
        for p in (tmp_path / "runs").glob("*.json")
    )


def test_request_limit_is_not_success(capture, tmp_path):
    run, config, _ = capture
    with pytest.raises(FetchFailure, match="REQUEST_LIMIT"):
        run(lambda _: page([work(1)], "next"), cfg=config.model_copy(update={"max_requests": 1}))
    assert (tmp_path / "snapshots/fixture/works.jsonl").is_file()


def test_bad_records_quarantined_and_empty_search_completes(capture, tmp_path):
    run, _, _ = capture
    manifest = run(lambda _: page([{"title": "Missing identifier"}, {"id": work(1)["id"]}]))
    assert manifest.quarantined_count == 2 and manifest.record_count == 0
    assert read_snapshot(tmp_path / "snapshots/fixture")[1] == {}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"results": [], "meta": {}}),
        page([work(1), work(2), work(3)]),
    ],
)
def test_malformed_response_fails(capture, response):
    run, _, _ = capture
    with pytest.raises(FetchFailure, match="INVALID_RESPONSE"):
        run(lambda _: response)


def test_retry_after_too_long_stops_without_retrying_early(capture):
    run, _, sleeps = capture
    with pytest.raises(FetchFailure, match="RETRY_AFTER_EXCEEDS"):
        run(lambda _: httpx.Response(429, headers={"Retry-After": "120"}))
    assert sleeps == []
    assert (
        _retry_delay(
            httpx.Response(429, headers={"Retry-After": "Wed, 01 Jan 2020 00:00:00 GMT"}), 0, 30
        )
        == 0
    )


def test_snapshot_path_traversal_rejected(capture, tmp_path):
    run, _, _ = capture
    with pytest.raises(ValueError):
        run(lambda _: page([]), name="../escape")
    assert not (tmp_path / "escape").exists()


def test_failure_on_second_page_preserves_partial_records(capture, tmp_path):
    run, _, _ = capture

    def handle(request):
        if request.url.params["cursor"] == "*":
            return page([work(1)], "second")
        return httpx.Response(503)

    with pytest.raises(FetchFailure, match="HTTP_503"):
        run(handle)
    directory = tmp_path / "snapshots/fixture"
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    assert manifest["record_count"] == 1 and manifest["status"] == "incomplete"
    assert json.loads((directory / "works.jsonl").read_text("utf-8")) == work(1)


def test_repeated_cursor_does_not_loop(capture):
    run, _, _ = capture
    with pytest.raises(FetchFailure, match="REPEATED_CURSOR"):
        run(lambda _: page([work(1)], "*"))


def test_keyboard_interrupt_preserves_incomplete_capture(capture, tmp_path):
    run, _, _ = capture

    def handle(request):
        if request.url.params["cursor"] == "*":
            return page([work(1)], "second")
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run(handle)
    directory = tmp_path / "snapshots/fixture"
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    assert manifest["status"] == "incomplete"
    assert manifest["errors"] == ["INTERRUPTED"]
    assert manifest["record_count"] == 1
    with pytest.raises(ValueError, match="completo"):
        read_snapshot(directory)
    records = [json.loads(p.read_text("utf-8")) for p in (tmp_path / "runs").glob("*.json")]
    assert records[0]["status"] == "failed"


def test_each_query_gets_its_budget_and_log_is_hash_checked(capture, tmp_path):
    run, config, _ = capture
    queries = [
        FetchSearch(query="with abstract", has_abstract=True, max_records=1),
        FetchSearch(query="without abstract", has_abstract=False, max_records=1),
    ]
    requests = []

    def handle(request):
        requests.append(request)
        return page([work(1)])

    manifest = run(handle, cfg=config.model_copy(update={"searches": queries}))
    assert manifest.record_count == manifest.duplicate_observations == 1
    assert "has_abstract:true" in requests[0].url.params["filter"]
    assert "has_abstract:false" in requests[1].url.params["filter"]
    directory = tmp_path / "snapshots/fixture"
    with (directory / "requests.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="Hash"):
        read_snapshot(directory)
