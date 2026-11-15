import json
import os
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.catalog.generations import pin_generation
from app.contracts import Bm25Config, GenerationManifest, PublicationReceipt, SearchParams
from app.core.config import Settings, embedding_config
from app.core.files import atomic_json, sha256_file
from app.indexing.build import build_generation, validate_collections, validate_patent_provenance
from app.indexing.publish import publish_generation
from app.recovery import backup, checked_path, restore, verify_backup
from app.search.service import search_documents
from qdrant_client import QdrantClient, models
from test_normalize import make_snapshot, review, work
from test_patent_corpus import selected  # noqa: F401
from test_search_flow import Encoder, ScopedClient


def model_fixture(root):
    config = embedding_config()
    folder = root / "models/multilingual-e5-small" / config.revision
    hashes = {}
    for name in (
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "modules.json",
        "1_Pooling/config.json",
    ):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic bytes; never loaded by an encoder", encoding="utf-8")
        hashes[name] = sha256_file(path)
    atomic_json(
        folder / "download.json",
        {"model_id": config.model_id, "revision": config.revision, "files": hashes},
    )


@pytest.fixture
def patent_bundle(tmp_path, selected, generation_manifest):  # noqa: F811
    root, _, selection = selected
    source = tmp_path / "bundle"
    data = source / "data"
    import shutil

    shutil.copytree(root / "patents", data / "patents")
    snapshot_root = data / "snapshots"
    snapshot_root.mkdir()
    snapshot, _ = make_snapshot(snapshot_root, [])
    for name in ("requests.jsonl", "quarantine.jsonl"):
        (snapshot / name).write_text("", encoding="utf-8")
    review_csv = source / "corpus/revision_corpus.csv"
    review_csv.parent.mkdir()
    review_csv.write_text("synthetic reviewed corpus", encoding="utf-8")
    manifest = generation_manifest().model_dump(mode="json")
    manifest.update(
        snapshot_id="synthetic",
        snapshot_sha256=sha256_file(snapshot / "works.jsonl"),
        review_csv_sha256=sha256_file(review_csv),
        publication_types=["patent"],
        patent_selection_sha256=sha256_file(selection),
        bm25=Bm25Config().model_dump(),
    )
    generation_dir = data / "generations" / manifest["generation_id"]
    atomic_json(generation_dir / "manifest.json", manifest)
    (generation_dir / "patent_selection.json").write_bytes(selection.read_bytes())
    atomic_json(
        generation_dir / "published.json",
        {
            "generation_id": manifest["generation_id"],
            "manifest_sha256": sha256_file(generation_dir / "manifest.json"),
            "published_at": datetime.now(UTC).isoformat(),
        },
    )
    atomic_json(source / "config/embedding.json", embedding_config().model_dump(mode="json"))
    for name in (
        "config/openalex.json",
        "pyproject.toml",
        "uv.lock",
        "compose.yaml",
        "qdrant/documents.snapshot",
        "qdrant/passages.snapshot",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    model_fixture(data)
    record = {
        "format": 1,
        "qdrant_version": "1.20.0",
        "generation": manifest["generation_id"],
        "aliases": {
            "documents": manifest["documents_collection"],
            "passages": manifest["passages_collection"],
        },
        "snapshots": {
            manifest["documents_collection"]: "qdrant/documents.snapshot",
            manifest["passages_collection"]: "qdrant/passages.snapshot",
        },
        "files": {
            p.relative_to(source).as_posix(): sha256_file(p)
            for p in source.rglob("*")
            if p.is_file()
        },
    }
    atomic_json(source / "backup.json", record)
    return source, generation_dir


@pytest.mark.parametrize("fault", [None, "selection", "xml", "removed_provenance"])
def test_patent_bundle_integrity(patent_bundle, fault):
    source, generation_dir = patent_bundle
    if fault is None:
        _, manifest = verify_backup(source)
        assert manifest.bm25 and manifest.patent_selection_sha256
        return
    if fault == "selection":
        (generation_dir / "patent_selection.json").write_text("altered", encoding="utf-8")
    elif fault == "xml":
        (source / "data/patents/snapshots/test_patent/page_0001.xml").write_text(
            "altered", encoding="utf-8"
        )
    else:
        manifest = json.loads((generation_dir / "manifest.json").read_text())
        manifest["patent_selection_sha256"] = None
        atomic_json(generation_dir / "manifest.json", manifest)
        receipt = json.loads((generation_dir / "published.json").read_text())
        receipt["manifest_sha256"] = sha256_file(generation_dir / "manifest.json")
        atomic_json(generation_dir / "published.json", receipt)
        record = json.loads((source / "backup.json").read_text())
        record["files"] = {n: sha256_file(source / n) for n in record["files"]}
        atomic_json(source / "backup.json", record)
    with pytest.raises(ValueError):
        restore(None, "unused", source, source.parent / "rejected")
    assert not (source.parent / "rejected").exists()


def test_manifest_requires_selection_in_both_directions(generation_manifest):
    for change in ({"publication_types": ["patent"]}, {"patent_selection_sha256": "a" * 64}):
        with pytest.raises(ValueError, match="procedencia"):
            GenerationManifest.model_validate(generation_manifest().model_dump() | change)


@pytest.mark.integration
def test_patent_bm25_backup_restore_roundtrip(tmp_path, selected):  # noqa: F811
    source_url, restore_url = os.getenv("QDRANT_TEST_URL"), os.getenv("QDRANT_RESTORE_TEST_URL")
    if not source_url or not restore_url or source_url == restore_url:
        pytest.skip("Requiere QDRANT_TEST_URL y QDRANT_RESTORE_TEST_URL exclusivo")
    root, _, selection = selected
    with (
        closing(QdrantClient(url=source_url, timeout=30)) as underlying,
        closing(QdrantClient(url=restore_url, timeout=30)) as recovered,
    ):
        if recovered.get_collections().collections or recovered.get_aliases().aliases:
            pytest.fail(
                "El servidor de restauración debe estar vacío; no se borran recursos ajenos"
            )
        original_aliases = underlying.get_aliases().model_dump()
        prefix = f"test_recovery_{uuid4().hex}_"
        client = ScopedClient(underlying, prefix)
        generation = f"test_recovery_{uuid4().hex}"
        settings = Settings(_env_file=None, ASISTENTE_DATA_DIR=root, qdrant_url=source_url)
        snapshots = root / "snapshots"
        snapshots.mkdir()
        snapshot, _ = make_snapshot(snapshots, [work(language="en", type="article")])
        for name in ("requests.jsonl", "quarantine.jsonl"):
            (snapshot / name).write_text("", encoding="utf-8")
        csv_path = root / "review.csv"
        review(snapshot, csv_path, ["incluir"])
        model_fixture(root)
        names = (f"documents_{generation}", f"passages_{generation}")
        try:
            build_generation(
                client,
                settings,
                embedding_config(),
                generation,
                snapshot,
                csv_path,
                Encoder,
                bm25=Bm25Config(),
                patent_selection=selection,
            )
            publish_generation(client, settings, embedding_config(), generation)
            source = root / "backup"
            backup(client, settings, embedding_config(), source, csv_path)
            assert (source / "config/epo_ops.json").is_file()
            _, manifest = verify_backup(source)
            restored = root / "restored"
            result = restore(recovered, restore_url, source, restored)
            assert result["documents"] == 2
            pinned = pin_generation(recovered, restored / "data", embedding_config())
            for mode in ("lexical", "hybrid"):
                found = search_documents(
                    recovered,
                    pinned,
                    Encoder(),
                    SearchParams(q="Synthetic", mode=mode, document_type="all"),
                )
                assert len(found.results) == 2
            # Schema and checksums alone cannot hide a changed patent catalogue.
            patent = next(
                d
                for d in search_documents(
                    recovered, pinned, Encoder(), SearchParams(q="title", document_type="patent")
                ).results
            )
            changed = patent.document.model_dump(mode="json") | {"title": "Altered catalogue"}
            recovered.set_payload(
                names[0], {"document": changed}, points=[str(patent.document.document_id)]
            )
            with pytest.raises(ValueError, match="Catálogo de patentes"):
                validate_patent_provenance(recovered, manifest, restored / "data")
            without = manifest.model_copy(update={"patent_selection_sha256": None})
            with pytest.raises(ValueError, match="procedencia"):
                validate_collections(recovered, without)
        finally:
            for db, alias_prefix in ((underlying, prefix), (recovered, "")):
                aliases = [
                    a.alias_name
                    for a in db.get_aliases().aliases
                    if a.collection_name in names
                    and a.alias_name in (alias_prefix + "documents", alias_prefix + "passages")
                ]
                if aliases:
                    db.update_collection_aliases(
                        [
                            models.DeleteAliasOperation(
                                delete_alias=models.DeleteAlias(alias_name=a)
                            )
                            for a in aliases
                        ]
                    )
                for name in names:
                    if db.collection_exists(name):
                        db.delete_collection(name)
            assert underlying.get_aliases().model_dump() == original_aliases


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
