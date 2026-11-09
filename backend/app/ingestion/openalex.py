import json
import os
import re
import time
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from app.contracts import FetchConfig, GenerationId, RunRecord, SnapshotManifest
from app.core.config import Settings
from app.core.files import atomic_json, sha256_file


class FetchFailure(ValueError):
    """Código público controlado; nunca contiene cuerpos, URLs ni secretos del proveedor."""


def _json_line(stream, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def _retry_delay(response: httpx.Response | None, attempt: int, maximum: float) -> float:
    delay = min(2**attempt, maximum)
    if response is not None and (header := response.headers.get("Retry-After")):
        try:
            delay = float(header)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header)
                delay = (retry_at - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                raise FetchFailure("INVALID_RETRY_AFTER") from None
        # No reintentar antes de lo solicitado por el proveedor.
        if delay > maximum or not float("-inf") < delay < float("inf"):
            raise FetchFailure("RETRY_AFTER_EXCEEDS_BUDGET")
    return max(0, delay)


def fetch_snapshot(
    settings: Settings, config: FetchConfig, snapshot_id: str, cutoff_date: date
) -> SnapshotManifest:
    snapshot_id = TypeAdapter(GenerationId).validate_python(snapshot_id)
    if cutoff_date < config.from_date:
        raise ValueError("Intervalo de captura invertido")
    if not settings.openalex_api_key:
        raise ValueError("Configura OPENALEX_API_KEY en .env")
    target = settings.data_dir / "snapshots" / snapshot_id
    # Crear exclusivamente: nunca truncar una captura previa, completa o incompleta.
    target.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC)
    manifest = SnapshotManifest(
        snapshot_id=snapshot_id,
        status="incomplete",
        searches=[search.query for search in config.searches],
        from_date=config.from_date,
        cutoff_date=cutoff_date,
        started_at=started,
        record_count=0,
        fetch_config=config,
    )
    run = RunRecord(
        run_id=f"fetch_{uuid4().hex}",
        operation="fetch",
        status="running",
        started_at=started,
        snapshot_id=snapshot_id,
    )
    run_path = settings.data_dir / "runs" / f"{run.run_id}.json"
    atomic_json(target / "manifest.json", manifest.model_dump(mode="json"))
    atomic_json(run_path, run.model_dump(mode="json"))
    seen: set[str] = set()
    failure: str | None = "INTERRUPTED"
    headers = {"Authorization": f"Bearer {settings.openalex_api_key.get_secret_value()}"}
    try:
        with (
            (target / "works.partial.jsonl").open("x", encoding="utf-8", newline="\n") as works,
            (target / "requests.jsonl").open("x", encoding="utf-8", newline="\n") as requests,
            (target / "quarantine.jsonl").open("x", encoding="utf-8", newline="\n") as quarantine,
            httpx.Client(
                base_url="https://api.openalex.org", headers=headers, timeout=config.timeout_seconds
            ) as client,
        ):
            for query_index, search in enumerate(config.searches):
                cursor = "*"
                cursors = {cursor}
                received = 0
                filters = ",".join(
                    [
                        f"from_publication_date:{config.from_date}",
                        f"to_publication_date:{cutoff_date}",
                        f"language:{'|'.join(config.languages)}",
                        f"has_abstract:{str(search.has_abstract).lower()}",
                    ]
                )
                while received < search.max_records:
                    params = {
                        "search": search.query,
                        "filter": filters,
                        "per_page": min(config.per_page, search.max_records - received),
                        "cursor": cursor,
                    }
                    response = None
                    for attempt in range(config.max_retries + 1):
                        if manifest.request_count >= config.max_requests:
                            raise FetchFailure("REQUEST_LIMIT_EXCEEDED")
                        if manifest.request_count:
                            time.sleep(config.request_interval_seconds)
                        manifest.request_count += 1
                        response = None
                        try:
                            response = client.get("/works", params=params)
                        except httpx.TransportError:
                            pass
                        status = response.status_code if response is not None else None
                        log = {
                            "query_index": query_index,
                            "params": params,
                            "attempt": attempt + 1,
                            "requested_at": datetime.now(UTC).isoformat(),
                            "status": status,
                        }
                        if status == 200:
                            try:
                                data = response.json()
                                results = data["results"]
                                next_cursor = data["meta"]["next_cursor"]
                                if (
                                    not isinstance(results, list)
                                    or len(results) > params["per_page"]
                                    or not (next_cursor is None or isinstance(next_cursor, str))
                                ):
                                    raise ValueError()
                            except (ValueError, KeyError, TypeError):
                                _json_line(requests, log | {"error": "INVALID_RESPONSE"})
                                raise FetchFailure("INVALID_RESPONSE") from None
                            ids = []
                            for work in results:
                                valid_id = (
                                    isinstance(work, dict)
                                    and isinstance(work.get("id"), str)
                                    and re.fullmatch(r"https://openalex.org/W[0-9]+", work["id"])
                                )
                                title = (
                                    work.get("title") or work.get("display_name")
                                    if isinstance(work, dict)
                                    else None
                                )
                                if not valid_id or not isinstance(title, str) or not title.strip():
                                    _json_line(
                                        quarantine,
                                        {
                                            "query_index": query_index,
                                            "reason": "MISSING_ID_OR_TITLE",
                                            "work": work,
                                        },
                                    )
                                    manifest.quarantined_count += 1
                                    continue
                                ids.append(work["id"])
                                if work["id"] in seen:
                                    manifest.duplicate_observations += 1
                                    continue
                                seen.add(work["id"])
                                _json_line(works, work)
                                manifest.record_count += 1
                            received += len(results)
                            stop = "record_limit" if received >= search.max_records else None
                            if not results or next_cursor is None:
                                stop = "exhausted"
                            _json_line(
                                requests,
                                log
                                | {
                                    "received_count": len(results),
                                    "ids": ids,
                                    "stop": stop,
                                },
                            )
                            break
                        _json_line(requests, log)
                        retryable = status is None or status in (408, 429, 500, 502, 503, 504)
                        if not retryable or attempt == config.max_retries:
                            raise FetchFailure(f"HTTP_{status}" if status else "TRANSPORT_ERROR")
                        time.sleep(_retry_delay(response, attempt, config.max_retry_wait_seconds))
                    if not results or next_cursor is None or received >= search.max_records:
                        break
                    if not next_cursor or next_cursor in cursors:
                        raise FetchFailure("REPEATED_CURSOR")
                    cursors.add(next_cursor)
                    cursor = next_cursor
            os.fsync(works.fileno())
            os.fsync(requests.fileno())
            os.fsync(quarantine.fileno())
        failure = None
    except FetchFailure as exc:
        failure = str(exc)
        raise
    except Exception:
        failure = "CAPTURE_FAILED"
        raise FetchFailure(failure) from None
    finally:
        # Aun un proceso interrumpido deja el manifiesto inicial incompleto.
        partial = target / "works.partial.jsonl"
        if partial.exists():
            partial.replace(target / "works.jsonl")
            manifest.works_sha256 = sha256_file(target / "works.jsonl")
        for filename, field in (
            ("requests.jsonl", "requests_sha256"),
            ("quarantine.jsonl", "quarantine_sha256"),
        ):
            if (target / filename).exists():
                setattr(manifest, field, sha256_file(target / filename))
        manifest.finished_at = datetime.now(UTC)
        manifest.status = "incomplete" if failure else "complete"
        manifest.errors = [failure] if failure else []
        # Revalidar antes de publicar el estado completo.
        manifest = SnapshotManifest.model_validate(manifest.model_dump())
        atomic_json(target / "manifest.json", manifest.model_dump(mode="json"))
        run.status = "failed" if failure else "succeeded"
        run.finished_at = manifest.finished_at
        run.error_code = failure
        atomic_json(run_path, run.model_dump(mode="json"))
    return manifest


def check_openalex(settings: Settings) -> dict:
    if not settings.openalex_api_key:
        raise ValueError("Configura OPENALEX_API_KEY en .env")
    # Authorization evita incluir la clave en URLs y mensajes de errores HTTP.
    headers = {"Authorization": f"Bearer {settings.openalex_api_key.get_secret_value()}"}
    with httpx.Client(base_url="https://api.openalex.org", headers=headers, timeout=20) as client:
        response = client.get(
            "/works",
            params={
                "search": "fall detection",
                "per_page": 1,
                "cursor": "*",
                "select": "id",
            },
        )
        if response.status_code != 200:
            raise ValueError(f"OpenAlex respondió HTTP {response.status_code}; revisa clave/cuota")
        data = response.json()
        if not isinstance(data.get("results"), list) or not data.get("meta", {}).get("next_cursor"):
            raise ValueError("OpenAlex no confirmó paginación por cursor")
        rate = client.get("/rate-limit")
        if rate.status_code != 200:
            raise ValueError(f"No se pudo verificar cuota OpenAlex (HTTP {rate.status_code})")
        # Selección explícita: nunca persistir respuesta cruda, headers ni credenciales.
        body = rate.json()
        quota = body.get("rate_limit", body)
        allowed = (
            "daily_budget_usd",
            "daily_remaining_usd",
            "daily_limit",
            "daily_remaining",
            "resets_at",
            "credits_remaining",
        )
        selected = {key: quota[key] for key in allowed if key in quota}
        if not any(key in selected for key in ("daily_remaining_usd", "credits_remaining")):
            raise ValueError("OpenAlex no devolvió una cuota reconocible")
        return {
            "authenticated_cursor": True,
            "quota_checked": True,
            "quota": selected,
        }
