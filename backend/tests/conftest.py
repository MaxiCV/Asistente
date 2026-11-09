from datetime import UTC, datetime

import pytest
from app.contracts import ChunkingConfig, GenerationManifest
from app.core.config import embedding_config


@pytest.fixture
def generation_manifest():
    def make(generation="test_generation"):
        return GenerationManifest(
            generation_id=generation,
            created_at=datetime.now(UTC),
            documents_collection=f"documents_{generation}",
            passages_collection=f"passages_{generation}",
            snapshot_id="test_snapshot",
            snapshot_sha256="a" * 64,
            review_csv_sha256="b" * 64,
            config_sha256="c" * 64,
            embedding=embedding_config(),
            chunking=ChunkingConfig(),
            document_count=1,
            passage_count=1,
            abstract_count=0,
            excluded_count=0,
            pending_count=0,
        )

    return make
