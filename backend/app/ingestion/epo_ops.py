"""Captura acotada de bibliografía OPS 3.2, sin publicar ni modificar Qdrant."""

import re
import time
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import httpx
from pydantic import TypeAdapter

from app.contracts import GenerationId, PatentDocument, PatentFetchConfig
from app.core.config import Settings
from app.core.files import atomic_json, sha256_file
from app.ingestion.openalex import FetchFailure, _retry_delay

BASE_URL = "https://ops.epo.org"
SEARCH_PATH = "/3.2/rest-services/published-data/search/biblio"
NS = {"ops": "http://ops.epo.org", "ex": "http://www.epo.org/exchange"}


def _text(node):
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _localized(nodes):
    # Conservar idioma real; no traducir ni mezclar versiones del resumen.
    for language in ("en", "es", None):
        for node in nodes:
            if (language is None or node.get("lang") == language) and _text(node):
                return node
    return None


def _names(bibliography, role):
    for format_name in ("original", "epodoc"):
        nodes = bibliography.findall(
            f"ex:parties/ex:{role}s/ex:{role}[@data-format='{format_name}']/ex:{role}-name/ex:name",
            NS,
        )
        names = list(dict.fromkeys(_text(node) for node in nodes if _text(node)))
        if names:
            return names
    return []


def parse_page(content: bytes, snapshot_id: str, retrieved_at: datetime):
    """XML UTF-8 de OPS. No se admiten DTD ni entidades definidas por terceros."""
    try:
        xml = content.decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper() or "\x00" in xml:
            raise ValueError()
        root = ET.fromstring(xml)
        search = root.find(".//ops:biblio-search", NS)
        if search is None:
            raise ValueError()
        total = int(search.attrib["total-result-count"])
        if total < 0:
            raise ValueError()
        documents = []
        for entry in search.findall(".//ex:exchange-document", NS):
            bibliography = entry.find("ex:bibliographic-data", NS)
            if bibliography is None:
                raise ValueError()
            identity = bibliography.find(
                "ex:publication-reference/ex:document-id[@document-id-type='docdb']", NS
            )
            if identity is None:
                raise ValueError()
            parts = [
                _text(identity.find(f"ex:{key}", NS)).upper()
                for key in ("country", "doc-number", "kind")
            ]
            publication_id = ".".join(parts)
            if not re.fullmatch(r"[A-Z]{2}\.[A-Z0-9]+\.[A-Z][0-9]?", publication_id):
                raise ValueError()
            raw_date = _text(identity.find("ex:date", NS))
            if raw_date and not re.fullmatch(r"\d{8}", raw_date):
                raise ValueError()
            title = _localized(bibliography.findall("ex:invention-title", NS))
            abstract = _localized(entry.findall("ex:abstract", NS))
            # Separar párrafos para evitar juntar palabras a través de etiquetas <p>.
            paragraphs = abstract.findall("ex:p", NS) if abstract is not None else []
            abstract_text = "\n\n".join(_text(p) for p in paragraphs if _text(p))
            abstract_text = abstract_text or _text(abstract) or None
            documents.append(
                PatentDocument(
                    publication_id=publication_id,
                    publication_date=date.fromisoformat(raw_date) if raw_date else None,
                    title=_text(title) or None,
                    language=title.get("lang") if title is not None else None,
                    abstract=abstract_text,
                    abstract_language=abstract.get("lang") if abstract is not None else None,
                    content_level="abstract" if abstract_text else "metadata",
                    source_url=f"{BASE_URL}/3.2/rest-services/published-data/publication/"
                    f"docdb/{publication_id}/biblio",
                    snapshot_id=snapshot_id,
                    retrieved_at=retrieved_at,
                    inventors=_names(bibliography, "inventor"),
                    applicants=_names(bibliography, "applicant"),
                )
            )
        return total, documents
    except (ValueError, KeyError, ET.ParseError):
        raise FetchFailure("OPS_INVALID_RESPONSE") from None


class OpsClient:
    def __init__(self, client: httpx.Client, settings: Settings, config: PatentFetchConfig):
        if not settings.epo_ops_consumer_key or not settings.epo_ops_consumer_secret:
            raise FetchFailure("OPS_CREDENTIALS_MISSING")
        self.client, self.settings, self.config = client, settings, config
        self.token = None
        self.expires_at = 0
        self.requests = []
        self.interval = config.request_interval_seconds
        self.blocked = False

    def request(self, method, path, **kwargs):
        for attempt in range(self.config.max_retries + 1):
            if self.blocked:
                raise FetchFailure("OPS_QUOTA_BLOCKED")
            if len(self.requests) >= self.config.max_requests:
                raise FetchFailure("OPS_REQUEST_LIMIT")
            if self.requests:
                time.sleep(self.interval)
            response = None
            try:
                response = self.client.request(method, path, **kwargs)
            except httpx.TransportError:
                pass
            status = response.status_code if response is not None else None
            log = {
                "operation": "token" if method == "POST" else "search",
                "status": status,
                "attempt": attempt + 1,
            }
            self.requests.append(log)
            if response is not None:
                throttle = re.search(
                    r"search=(green|yellow|red|black):(\d+)",
                    response.headers.get("X-Throttling-Control", ""),
                )
                if throttle:
                    color, limit = throttle.group(1), int(throttle.group(2))
                    log["search_throttle"] = {"state": color, "limit": limit}
                    self.blocked = color == "black" or limit == 0
                    if limit:
                        self.interval = max(self.interval, 60 / limit)
                if status == 403 or self.blocked:
                    raise FetchFailure("OPS_QUOTA_OR_ACCESS_DENIED")
                if status not in (408, 429, 500, 502, 503, 504):
                    return response
            if attempt == self.config.max_retries:
                raise FetchFailure(f"OPS_HTTP_{status}" if status else "OPS_TRANSPORT_ERROR")
            # Nunca acortar Retry-After; si supera el presupuesto, abortar la captura.
            time.sleep(_retry_delay(response, attempt, self.config.max_retry_wait_seconds))
        raise AssertionError("unreachable")

    def authenticate(self):
        response = self.request(
            "POST",
            "/3.2/auth/accesstoken",
            auth=httpx.BasicAuth(
                self.settings.epo_ops_consumer_key.get_secret_value(),
                self.settings.epo_ops_consumer_secret.get_secret_value(),
            ),
            data={"grant_type": "client_credentials"},
        )
        if response.status_code != 200:
            raise FetchFailure(f"OPS_AUTH_HTTP_{response.status_code}")
        try:
            body = response.json()
            token, expires = body["access_token"], int(body["expires_in"])
            if (
                not isinstance(token, str)
                or not re.fullmatch(r"[\x21-\x7e]+", token)
                or expires <= 0
            ):
                raise ValueError()
            self.token = token
            self.expires_at = time.monotonic() + max(0, expires - 30)
        except (ValueError, KeyError, TypeError):
            raise FetchFailure("OPS_INVALID_TOKEN_RESPONSE") from None

    def search(self, start, end):
        for refresh in range(2):
            if self.token is None or time.monotonic() >= self.expires_at:
                self.authenticate()
            response = self.request(
                "GET",
                SEARCH_PATH,
                params={"q": self.config.query, "Range": f"{start}-{end}"},
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/xml"},
            )
            if response.status_code == 401 and refresh == 0:
                self.token = None
                continue
            if response.status_code != 200:
                raise FetchFailure(f"OPS_HTTP_{response.status_code}")
            return response.content
        raise FetchFailure("OPS_AUTH_FAILED")


def fetch_patents(settings: Settings, config: PatentFetchConfig, snapshot_id: str) -> dict:
    snapshot_id = TypeAdapter(GenerationId).validate_python(snapshot_id)
    if not settings.epo_ops_consumer_key or not settings.epo_ops_consumer_secret:
        raise FetchFailure("OPS_CREDENTIALS_MISSING")
    target = settings.data_dir / "patents" / "snapshots" / snapshot_id
    target.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "source": "epo_ops",
        "snapshot_id": snapshot_id,
        "status": "incomplete",
        "started_at": datetime.now(UTC).isoformat(),
        "config": config.model_dump(mode="json"),
        "record_count": 0,
        "duplicate_observations": 0,
        "files": {},
        "error_code": "INTERRUPTED",
    }
    from app.contracts import PatentSnapshotManifest

    PatentSnapshotManifest.model_validate(manifest)
    atomic_json(target / "manifest.json", manifest)
    ops = None
    seen = set()
    try:
        with httpx.Client(
            base_url=BASE_URL, timeout=config.timeout_seconds, follow_redirects=False
        ) as client:
            ops = OpsClient(client, settings, config)
            with (target / "patents.jsonl").open("x", encoding="utf-8") as output:
                start = 1
                while start <= config.max_records:
                    end = min(start + config.page_size - 1, config.max_records)
                    content = ops.search(start, end)
                    retrieved_at = datetime.now(UTC)
                    total, documents = parse_page(content, snapshot_id, retrieved_at)
                    expected = max(0, min(end, total) - start + 1)
                    if len(documents) != expected:
                        raise FetchFailure("OPS_UNEXPECTED_PAGE_SIZE")
                    filename = f"page_{start:04d}.xml"
                    (target / filename).write_bytes(content)
                    manifest["files"][filename] = sha256_file(target / filename)
                    for document in documents:
                        if document.publication_id in seen:
                            manifest["duplicate_observations"] += 1
                            continue
                        seen.add(document.publication_id)
                        output.write(document.model_dump_json() + "\n")
                        manifest["record_count"] += 1
                    manifest["total_results_reported"] = total
                    if end >= total or end >= config.max_records:
                        manifest["stop_reason"] = "exhausted" if end >= total else "record_limit"
                        break
                    start = end + 1
        manifest.update(status="complete", error_code=None)
    except FetchFailure as exc:
        manifest["error_code"] = str(exc)
        raise
    except Exception:
        manifest["error_code"] = "OPS_CAPTURE_FAILED"
        raise FetchFailure("OPS_CAPTURE_FAILED") from None
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        manifest["requests"] = ops.requests if ops else []
        if (target / "patents.jsonl").exists():
            manifest["files"]["patents.jsonl"] = sha256_file(target / "patents.jsonl")
        PatentSnapshotManifest.model_validate(manifest)
        atomic_json(target / "manifest.json", manifest)
    return manifest
