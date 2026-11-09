"""Portable, checked backup of the active generation; restore into empty destinations only."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx
from qdrant_client import models

from app.catalog.generations import collection_names, pin_generation, read_generation
from app.contracts import EmbeddingConfig
from app.core.config import ROOT, Settings
from app.core.files import atomic_json, sha256_file
from app.embeddings.local import MODEL_FILES, verify_model_files
from app.indexing.build import validate_collections, writer_lock
from app.ingestion.snapshot import read_snapshot


def checked_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Ruta de respaldo inválida")
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Ruta fuera del respaldo")
    if any(p.is_symlink() for p in (target, *target.parents) if p != root.parent):
        raise ValueError("No se admiten enlaces en el respaldo")
    return target


def _copy(source, destination):
    if source.is_symlink():
        raise ValueError("No se respaldan enlaces")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def backup(client, settings, config, destination: Path, review_csv: Path):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("El destino del respaldo debe ser nuevo")
    with writer_lock(settings.data_dir):
        pinned = pin_generation(client, settings.data_dir, config)
        manifest = pinned.manifest
        if client.info().version != "1.20.0":
            raise ValueError("Se requiere Qdrant 1.20.0")
        validate_collections(client, manifest)
        if sha256_file(review_csv) != manifest.review_csv_sha256:
            raise ValueError("CSV distinto del usado para construir la generación")
        folder = settings.data_dir / "generations" / pinned.generation_id
        read_generation(settings.data_dir, config, pinned.generation_id, require_publication=True)
        snapshot = settings.data_dir / "snapshots" / manifest.snapshot_id
        read_snapshot(snapshot)
        if sha256_file(snapshot / "works.jsonl") != manifest.snapshot_sha256:
            raise ValueError("Snapshot distinto del usado para construir la generación")
        model = verify_model_files(settings, config)
        destination.mkdir(parents=True)
        files = {}

        def copy(source, name):
            target = checked_path(destination, name)
            _copy(source, target)
            files[name] = sha256_file(target)

        for filename in ("manifest.json", "published.json", "build.json"):
            if (folder / filename).is_file():
                copy(folder / filename, f"data/generations/{pinned.generation_id}/{filename}")
        for filename in ("manifest.json", "works.jsonl", "requests.jsonl", "quarantine.jsonl"):
            copy(snapshot / filename, f"data/snapshots/{manifest.snapshot_id}/{filename}")
        for filename in [*MODEL_FILES, "download.json"]:
            if (model / filename).is_file():
                copy(
                    model / filename,
                    f"data/models/multilingual-e5-small/{config.revision}/{filename}",
                )
        for path in sorted((settings.data_dir / "runs").glob("*.json")):
            copy(path, f"data/runs/{path.name}")
        copy(review_csv, "corpus/revision_corpus.csv")
        for filename in ("embedding.json", "openalex.json"):
            copy(ROOT / "config" / filename, f"config/{filename}")
        for filename in ("pyproject.toml", "uv.lock", "compose.yaml"):
            copy(ROOT / filename, filename)
        snapshots = {}
        with httpx.Client(base_url=settings.qdrant_url, timeout=120) as http:
            for name in collection_names(pinned.generation_id):
                created = client.create_snapshot(name, wait=True)
                endpoint = f"/collections/{name}/snapshots/{quote(created.name, safe='')}"
                relative = f"qdrant/{name}.snapshot"
                target = checked_path(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with http.stream("GET", endpoint) as response, target.open("xb") as stream:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
                files[relative] = sha256_file(target)
                snapshots[name] = relative
                client.delete_snapshot(name, created.name, wait=True)
        if pin_generation(client, settings.data_dir, config).generation_id != pinned.generation_id:
            raise ValueError("La generación cambió durante el respaldo")
        result = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "qdrant_version": "1.20.0",
            "generation": pinned.generation_id,
            "aliases": dict(
                zip(("documents", "passages"), collection_names(pinned.generation_id), strict=True)
            ),
            "snapshots": snapshots,
            "files": files,
        }
        atomic_json(destination / "backup.json", result)
        return {"backup": str(destination), "generation": pinned.generation_id, "files": len(files)}


def verify_backup(source: Path):
    record = json.loads((source / "backup.json").read_text("utf-8"))
    if record["format"] != 1 or record["qdrant_version"] != "1.20.0":
        raise ValueError("Formato o versión de respaldo incompatible")
    names = collection_names(record["generation"])
    required = {
        "config/embedding.json",
        "config/openalex.json",
        "corpus/revision_corpus.csv",
        "pyproject.toml",
        "uv.lock",
        "compose.yaml",
        f"data/generations/{record['generation']}/manifest.json",
        f"data/generations/{record['generation']}/published.json",
    }
    if not required.issubset(record["files"]):
        raise ValueError("Respaldo incompleto")
    if record["aliases"] != dict(zip(("documents", "passages"), names, strict=True)):
        raise ValueError("Alias incoherentes")
    if set(record["snapshots"]) != set(names):
        raise ValueError("Pareja de snapshots incompleta")
    for name, expected in record["files"].items():
        if sha256_file(checked_path(source, name)) != expected:
            raise ValueError(f"Hash de respaldo inválido: {name}")
    for name in record["snapshots"].values():
        if name not in record["files"]:
            raise ValueError("Snapshot sin checksum")
    config = EmbeddingConfig.model_validate_json((source / "config/embedding.json").read_text())
    manifest = read_generation(
        source / "data", config, record["generation"], require_publication=True
    ).manifest
    model = verify_model_files(Settings(_env_file=None, ASISTENTE_DATA_DIR=source / "data"), config)
    download = json.loads((model / "download.json").read_text())
    required.update(
        f"data/models/multilingual-e5-small/{config.revision}/{name}"
        for name in [*download["files"], "download.json"]
    )
    required.update(
        f"data/snapshots/{manifest.snapshot_id}/{name}"
        for name in ("manifest.json", "works.jsonl", "requests.jsonl", "quarantine.jsonl")
    )
    if not required.issubset(record["files"]):
        raise ValueError("Respaldo incompleto")
    read_snapshot(source / "data/snapshots" / manifest.snapshot_id)
    if sha256_file(source / "data/snapshots" / manifest.snapshot_id / "works.jsonl") != (
        manifest.snapshot_sha256
    ):
        raise ValueError("Snapshot de respaldo incompatible")
    if sha256_file(source / "corpus/revision_corpus.csv") != manifest.review_csv_sha256:
        raise ValueError("CSV de respaldo incompatible")
    return record, manifest


def restore(client, qdrant_url: str, source: Path, destination: Path):
    # All local checks happen before any writes to the destination or database.
    record, manifest = verify_backup(source)
    if destination.exists():
        raise ValueError("El directorio de restauración debe ser nuevo")
    if client.info().version != record["qdrant_version"]:
        raise ValueError("Versión Qdrant incompatible")
    if client.get_collections().collections or client.get_aliases().aliases:
        raise ValueError("La restauración requiere un Qdrant vacío y exclusivo")
    destination.mkdir(parents=True)
    for name in record["files"]:
        if not name.startswith("qdrant/"):
            _copy(checked_path(source, name), checked_path(destination, name))
    with httpx.Client(base_url=qdrant_url, timeout=180) as http:
        for collection, name in record["snapshots"].items():
            with checked_path(source, name).open("rb") as stream:
                response = http.post(
                    f"/collections/{collection}/snapshots/upload",
                    params={"wait": "true", "priority": "snapshot"},
                    files={"snapshot": (Path(name).name, stream, "application/octet-stream")},
                )
                response.raise_for_status()
    validate_collections(client, manifest)
    client.update_collection_aliases(
        [
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(alias_name=alias, collection_name=collection)
            )
            for alias, collection in record["aliases"].items()
        ]
    )
    pinned = pin_generation(client, destination / "data", manifest.embedding)
    result = {
        "restored": pinned.generation_id,
        "documents": manifest.document_count,
        "passages": manifest.passage_count,
        "destination": str(destination.resolve()),
    }
    atomic_json(destination / "restore.json", result)
    return result
