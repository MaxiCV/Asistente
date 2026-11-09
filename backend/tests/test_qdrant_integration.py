import os
from uuid import uuid4

import pytest
from app.catalog.generations import create_candidate_collections
from app.core.config import embedding_config
from app.core.qdrant import qdrant_connection
from qdrant_client import models


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("QDRANT_TEST_URL"), reason="QDRANT_TEST_URL no configurado")
def test_real_qdrant_payload_only_vectors_indexes_and_alias_protection():
    generation = f"test_{uuid4().hex}"
    aliases = [f"test_documents_{generation}", f"test_passages_{generation}"]
    names = (f"documents_{generation}", f"passages_{generation}")
    with qdrant_connection(os.environ["QDRANT_TEST_URL"], timeout=10) as client:
        try:
            assert create_candidate_collections(client, generation, embedding_config()) == names
            assert create_candidate_collections(client, generation, embedding_config()) == names
            point_id = str(uuid4())
            payload = {
                "document_id": point_id,
                "document_type": "publication",
                "publication_type": "article",
                "publication_date": "2026-01-01T00:00:00Z",
            }
            client.upsert(
                names[0], [models.PointStruct(id=point_id, vector={}, payload=payload)], wait=True
            )
            client.upsert(
                names[1],
                [
                    models.PointStruct(
                        id=point_id,
                        vector={"dense": [1.0] + [0.0] * 383},
                        payload=payload,
                    )
                ],
                wait=True,
            )
            client.update_collection_aliases(
                change_aliases_operations=[
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            collection_name=name,
                            alias_name=alias,
                        )
                    )
                    for name, alias in zip(names, aliases, strict=True)
                ]
            )
            with pytest.raises(ValueError, match="publicada"):
                create_candidate_collections(client, generation, embedding_config())
            with qdrant_connection(os.environ["QDRANT_TEST_URL"]) as reader:
                assert reader.count(names[0], exact=True).count == 1
                assert reader.count(names[1], exact=True).count == 1
                assert set(reader.get_collection(names[1]).payload_schema) >= {
                    "document_id",
                    "publication_date",
                    "publication_type",
                    "document_type",
                }
                assert reader.retrieve(names[0], [point_id])[0].payload["document_id"] == point_id
        finally:
            # Solo nombres únicos creados por esta prueba; nunca alias del corpus.
            existing = {a.alias_name for a in client.get_aliases().aliases}
            deletes = [
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=a))
                for a in aliases
                if a in existing
            ]
            if deletes:
                client.update_collection_aliases(change_aliases_operations=deletes)
            for name in names:
                if client.collection_exists(name):
                    client.delete_collection(name)
