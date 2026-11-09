import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.contracts import PublicationReceipt
from app.core.config import embedding_config
from app.core.files import atomic_json, sha256_file
from app.recovery import checked_path, restore, verify_backup


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/drive", "data\\escape"])
def test_recovery_rejects_paths_outside_bundle(tmp_path, name):
    with pytest.raises(ValueError, match="Ruta"):
        checked_path(tmp_path, name)


def test_corrupt_backup_is_rejected_before_connecting_or_writing(tmp_path):
    source = tmp_path / "backup"
    source.mkdir()
    names = [
        "config/embedding.json",
        "config/openalex.json",
        "corpus/revision_corpus.csv",
        "pyproject.toml",
        "uv.lock",
        "compose.yaml",
        "data/generations/test/manifest.json",
        "data/generations/test/published.json",
        "qdrant/documents.snapshot",
        "qdrant/passages.snapshot",
    ]
    hashes = {}
    for name in names:
        path = checked_path(source, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original", encoding="utf-8")
        hashes[name] = sha256_file(path)
    record = {
        "format": 1,
        "qdrant_version": "1.20.0",
        "generation": "test",
        "aliases": {"documents": "documents_test", "passages": "passages_test"},
        "snapshots": {"documents_test": names[-2], "passages_test": names[-1]},
        "files": hashes,
    }
    atomic_json(source / "backup.json", record)
    (source / "config/embedding.json").write_text("altered", encoding="utf-8")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="Hash"):
        restore(None, "unused", source, destination)
    assert not destination.exists()
    record = json.loads((source / "backup.json").read_text())
    del record["files"]["config/embedding.json"]
    atomic_json(source / "backup.json", record)
    with pytest.raises(ValueError, match="incompleto"):
        verify_backup(source)


def test_restore_refuses_nonempty_database_without_creating_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.recovery.verify_backup", lambda _: ({"qdrant_version": "1.20.0"}, None)
    )
    client = SimpleNamespace(
        info=lambda: SimpleNamespace(version="1.20.0"),
        get_collections=lambda: SimpleNamespace(collections=["important"]),
    )
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="vacío"):
        restore(client, "unused", tmp_path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("fault", ["generation_id", "manifest_sha256", "malformed"])
def test_invalid_publication_in_rehashed_backup_is_rejected_before_writes(
    tmp_path, generation_manifest, fault
):
    source = tmp_path / "backup"
    manifest = generation_manifest()
    folder = source / "data/generations" / manifest.generation_id
    atomic_json(folder / "manifest.json", manifest.model_dump(mode="json"))
    receipt = PublicationReceipt(
        generation_id=manifest.generation_id,
        manifest_sha256=sha256_file(folder / "manifest.json"),
        published_at=datetime.now(UTC),
    ).model_dump(mode="json")
    if fault == "malformed":
        (folder / "published.json").write_text("invalid", encoding="utf-8")
    else:
        receipt[fault] = "other" if fault == "generation_id" else "f" * 64
        atomic_json(folder / "published.json", receipt)
    atomic_json(source / "config/embedding.json", embedding_config().model_dump(mode="json"))
    for name in (
        "config/openalex.json",
        "corpus/revision_corpus.csv",
        "pyproject.toml",
        "uv.lock",
        "compose.yaml",
        "qdrant/documents.snapshot",
        "qdrant/passages.snapshot",
    ):
        path = checked_path(source, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture", encoding="utf-8")
    # Los checksums del contenedor son válidos; la relación recibo/manifiesto no.
    record = {
        "format": 1,
        "qdrant_version": "1.20.0",
        "generation": manifest.generation_id,
        "aliases": {
            "documents": manifest.documents_collection,
            "passages": manifest.passages_collection,
        },
        "snapshots": {
            manifest.documents_collection: "qdrant/documents.snapshot",
            manifest.passages_collection: "qdrant/passages.snapshot",
        },
        "files": {
            path.relative_to(source).as_posix(): sha256_file(path)
            for path in source.rglob("*")
            if path.is_file()
        },
    }
    atomic_json(source / "backup.json", record)
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="Registro de publicación|Manifiesto publicado"):
        restore(None, "unused", source, destination)
    assert not destination.exists()
