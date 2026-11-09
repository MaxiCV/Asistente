from datetime import UTC, datetime
from uuid import uuid4

from qdrant_client import models

from app.catalog.generations import (
    collection_names,
    pin_active_generation,
    read_generation,
    record_publication,
)
from app.contracts import RunRecord
from app.core.files import atomic_json
from app.indexing.build import validate_collections, writer_lock


def publish_generation(client, settings, embedding, generation, *, rollback=False):
    names = collection_names(generation)
    with writer_lock(settings.data_dir):
        run = RunRecord(
            run_id=f"publish_{uuid4().hex}",
            operation="rollback" if rollback else "publish",
            status="running",
            started_at=datetime.now(UTC),
            generation_id=generation,
        )
        path = settings.data_dir / "runs" / f"{run.run_id}.json"
        atomic_json(path, run.model_dump(mode="json"))
        try:
            record = read_generation(
                settings.data_dir, embedding, generation, require_publication=rollback
            )
            validate_collections(client, record.manifest)
            aliases = {a.alias_name: a.collection_name for a in client.get_aliases().aliases}
            if "documents" in aliases or "passages" in aliases:
                previous = pin_active_generation(client, settings.data_dir, embedding)
                record_publication(settings.data_dir, embedding, previous.generation_id)
            operations = [
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=a))
                for a in ("documents", "passages")
                if a in aliases
            ]
            operations += [
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        alias_name=a,
                        collection_name=name,
                    )
                )
                for a, name in zip(("documents", "passages"), names, strict=True)
            ]
            try:
                client.update_collection_aliases(change_aliases_operations=operations)
            except Exception:
                # Una respuesta incierta no autoriza borrar ni reconstruir la candidata.
                current = {a.alias_name: a.collection_name for a in client.get_aliases().aliases}
                if (current.get("documents"), current.get("passages")) != names:
                    raise ValueError(
                        "Publicación no confirmada; revisar alias antes de reintentar"
                    ) from None
            current = pin_active_generation(client, settings.data_dir, embedding)
            if current.generation_id != generation:
                raise ValueError("No se confirmó la generación publicada")
            record_publication(settings.data_dir, embedding, generation)
            run.status = "succeeded"
        except BaseException:
            run.status = "failed"
            run.error_code = "publication_unconfirmed"
            raise
        finally:
            run.finished_at = datetime.now(UTC)
            atomic_json(path, run.model_dump(mode="json"))
        return {"published": generation, "operation": run.operation}
