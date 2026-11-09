import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.catalog.generations import (
    GenerationRetired,
    GenerationUnavailable,
    pin_active_generation,
    pin_generation,
)
from app.contracts import PublicationReceipt
from app.core.config import embedding_config
from app.core.files import atomic_json, sha256_file


class AliasClient:
    def __init__(self, generation="test_generation"):
        self.calls = 0
        self.names = {"documents": f"documents_{generation}", "passages": f"passages_{generation}"}

    def get_aliases(self):
        self.calls += 1
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=k, collection_name=v) for k, v in self.names.items()
            ]
        )


@pytest.mark.parametrize("receipt_contents", [None, "invalid receipt"])
def test_pins_one_alias_snapshot_and_keeps_physical_names(
    tmp_path, generation_manifest, receipt_contents
):
    manifest = generation_manifest()
    path = tmp_path / "generations/test_generation"
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    if receipt_contents is not None:
        (path / "published.json").write_text(receipt_contents, encoding="utf-8")
    client = AliasClient()
    pinned = pin_active_generation(client, tmp_path, embedding_config())
    client.names = {"documents": "documents_other", "passages": "passages_other"}
    assert client.calls == 1
    assert pinned.documents_collection == "documents_test_generation"
    assert pinned.passages_collection == "passages_test_generation"
    if receipt_contents is None:
        assert not (path / "published.json").exists()
    else:
        assert (path / "published.json").read_text("utf-8") == receipt_contents


def test_rejects_mixed_aliases_and_missing_manifest(tmp_path):
    client = AliasClient()
    client.names["passages"] = "passages_other"
    with pytest.raises(GenerationUnavailable):
        pin_active_generation(client, tmp_path, embedding_config())
    with pytest.raises(GenerationUnavailable):
        pin_active_generation(AliasClient(), tmp_path, embedding_config())


def test_rejects_model_mismatch(tmp_path, generation_manifest):
    manifest = generation_manifest()
    path = tmp_path / "generations/test_generation"
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(manifest.model_dump_json(), "utf-8")
    different = embedding_config().model_copy(update={"revision": "f" * 40})
    with pytest.raises(GenerationUnavailable, match="incompatible"):
        pin_active_generation(AliasClient(), tmp_path, different)


class CollectionClient(AliasClient):
    missing_collection = None

    def collection_exists(self, name):
        return name != self.missing_collection


@pytest.fixture
def published_generation(tmp_path, generation_manifest):
    manifest = generation_manifest()
    folder = tmp_path / "generations" / manifest.generation_id
    atomic_json(folder / "manifest.json", manifest.model_dump(mode="json"))
    receipt = PublicationReceipt(
        generation_id=manifest.generation_id,
        manifest_sha256=sha256_file(folder / "manifest.json"),
        published_at=datetime(2026, 11, 5, tzinfo=UTC),
    )
    atomic_json(folder / "published.json", receipt.model_dump(mode="json"))
    return folder


def test_historical_generation_is_readable_despite_mixed_active_aliases(
    tmp_path, published_generation
):
    client = CollectionClient("other")
    client.names["passages"] = "passages_mixed"
    pinned = pin_generation(client, tmp_path, embedding_config(), published_generation.name)
    assert pinned.generation_id == published_generation.name
    assert client.calls == 1


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("missing_receipt_and_manifest", GenerationRetired),
        ("invalid_receipt", GenerationRetired),
        ("foreign_receipt_and_missing_manifest", GenerationUnavailable),
        ("missing_manifest", GenerationRetired),
        ("changed_manifest", GenerationUnavailable),
        ("incompatible_model", GenerationUnavailable),
        ("foreign_manifest", GenerationUnavailable),
        ("missing_collection", GenerationRetired),
    ],
)
def test_historical_publication_failures_keep_their_meaning(
    tmp_path, published_generation, generation_manifest, fault, error
):
    folder = published_generation
    manifest_path, receipt_path = folder / "manifest.json", folder / "published.json"
    config = embedding_config()
    client = CollectionClient("other")
    if fault == "missing_receipt_and_manifest":
        receipt_path.unlink()
        manifest_path.unlink()
    elif fault == "invalid_receipt":
        receipt_path.write_text("invalid", encoding="utf-8")
    elif fault == "foreign_receipt_and_missing_manifest":
        receipt = json.loads(receipt_path.read_text("utf-8"))
        receipt["generation_id"] = "other"
        atomic_json(receipt_path, receipt)
        manifest_path.unlink()
    elif fault == "missing_manifest":
        manifest_path.unlink()
    elif fault == "changed_manifest":
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    elif fault == "incompatible_model":
        config = config.model_copy(update={"revision": "f" * 40})
    elif fault == "foreign_manifest":
        atomic_json(manifest_path, generation_manifest("other").model_dump(mode="json"))
        receipt = json.loads(receipt_path.read_text("utf-8"))
        receipt["manifest_sha256"] = sha256_file(manifest_path)
        atomic_json(receipt_path, receipt)
    else:
        client.missing_collection = f"passages_{folder.name}"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(error):
        pin_generation(client, tmp_path, config, folder.name)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("explicit", [False, True])
def test_missing_active_collection_distinguishes_new_and_pinned_queries(
    tmp_path, published_generation, explicit
):
    client = CollectionClient(published_generation.name)
    client.missing_collection = f"passages_{published_generation.name}"
    with pytest.raises(GenerationRetired if explicit else GenerationUnavailable):
        pin_generation(
            client,
            tmp_path,
            embedding_config(),
            published_generation.name if explicit else None,
        )
