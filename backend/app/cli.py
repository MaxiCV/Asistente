import argparse
import json
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from app.core.config import ROOT, Settings, embedding_config
from app.core.qdrant import qdrant_connection


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantenimiento del buscador local")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Crear directorios persistentes; no modifica corpus")
    commands.add_parser("check-env", help="Comprobar Qdrant y configuración sin revelar secretos")
    commands.add_parser("check-openalex", help="Verificar autenticación, cursor y cuota reales")
    commands.add_parser("prepare-model", help="Descargar revisión fijada y registrar hashes")
    commands.add_parser("check-model", help="Cargar y vectorizar ES/EN exclusivamente offline")
    commands.add_parser("export-schemas", help="Exportar contratos JSON Schema y OpenAPI")
    collections = commands.add_parser(
        "create-collections", help="Crear pareja candidata sin publicar"
    )
    collections.add_argument("generation")
    review = commands.add_parser("validate-review", help="Validar CSV contra snapshot completo")
    review.add_argument("--csv", type=Path, default=ROOT / "corpus/revision_corpus.csv")
    review.add_argument("--snapshot", type=Path, required=True)
    fetch = commands.add_parser("fetch", help="Capturar un lote acotado de OpenAlex, sin indexar")
    fetch.add_argument("snapshot_id")
    fetch.add_argument("--config", type=Path, default=ROOT / "config/openalex.json")
    fetch.add_argument("--cutoff", type=date.fromisoformat, required=True)
    draft = commands.add_parser(
        "prepare-review", help="Crear un CSV nuevo con decisiones pendientes"
    )
    draft.add_argument("--snapshot", type=Path, required=True)
    draft.add_argument("--csv", type=Path, required=True)
    draft.add_argument("--date", type=date.fromisoformat, required=True)
    normalize = commands.add_parser("normalize", help="Normalizar offline; --csv aplica selección")
    normalize.add_argument("--snapshot", type=Path, required=True)
    normalize.add_argument("--output", type=Path, required=True)
    normalize.add_argument("--csv", type=Path)
    build = commands.add_parser("build", help="Construir una generación nueva desde snapshot y CSV")
    build.add_argument("generation")
    build.add_argument("--snapshot", type=Path, required=True)
    build.add_argument("--csv", type=Path, default=ROOT / "corpus/revision_corpus.csv")
    for command in ("publish", "rollback"):
        publication = commands.add_parser(
            command, help="Cambiar ambos alias a una generación validada"
        )
        publication.add_argument("generation")
    backup = commands.add_parser("backup", help="Respaldar generación activa y modelo local")
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--csv", type=Path, default=ROOT / "corpus/revision_corpus.csv")
    restore = commands.add_parser("restore", help="Restaurar en Qdrant vacío y directorio nuevo")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    config = embedding_config()
    try:
        if args.command == "init":
            for name in ("snapshots", "generations", "runs", "models", "checks"):
                (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
            result = {"initialized": True}
        elif args.command == "check-env":
            with qdrant_connection(settings.qdrant_url) as client:
                info = client.info()
            result = {
                "qdrant": info.version,
                "model_revision": config.revision,
                "openalex_key_configured": bool(settings.openalex_api_key),
            }
        elif args.command in ("backup", "restore"):
            from app.recovery import backup, restore

            with qdrant_connection(settings.qdrant_url, timeout=180) as client:
                result = (
                    backup(client, settings, config, args.output, args.csv)
                    if args.command == "backup"
                    else restore(client, settings.qdrant_url, args.backup, args.output)
                )
        elif args.command == "check-openalex":
            from app.ingestion.openalex import check_openalex

            result = check_openalex(settings)
        elif args.command == "prepare-model":
            from app.embeddings.local import download_model

            result = download_model(settings, config)
        elif args.command == "check-model":
            from app.embeddings.local import check_model

            result = check_model(settings, config)
        elif args.command == "create-collections":
            from app.catalog.generations import create_candidate_collections

            with qdrant_connection(settings.qdrant_url, timeout=10) as client:
                names = create_candidate_collections(client, args.generation, config)
            result = {"candidate_collections": names, "published": False}
        elif args.command == "fetch":
            from app.contracts import FetchConfig
            from app.ingestion.openalex import fetch_snapshot

            fetch_config = FetchConfig.model_validate_json(args.config.read_text("utf-8"))
            result = fetch_snapshot(
                settings, fetch_config, args.snapshot_id, args.cutoff
            ).model_dump(mode="json")
        elif args.command == "prepare-review":
            from app.ingestion.normalize import prepare_review

            result = prepare_review(args.snapshot, args.csv, args.date)
        elif args.command == "normalize":
            from app.ingestion.normalize import export_documents

            result = export_documents(args.snapshot, args.output, args.csv)
        elif args.command == "validate-review":
            from app.ingestion.normalize import select_documents

            _, result = select_documents(args.snapshot, args.csv)
        elif args.command == "build":
            from app.embeddings.local import LocalEncoder
            from app.indexing.build import build_generation

            with qdrant_connection(settings.qdrant_url, timeout=60) as client:
                result = build_generation(
                    client, settings, config, args.generation, args.snapshot, args.csv, LocalEncoder
                )
        elif args.command in ("publish", "rollback"):
            from app.indexing.publish import publish_generation

            with qdrant_connection(settings.qdrant_url, timeout=60) as client:
                result = publish_generation(
                    client, settings, config, args.generation, rollback=args.command == "rollback"
                )
        else:
            from app import contracts
            from app.core.files import atomic_json
            from app.main import create_app

            target = ROOT / "docs/contracts"
            names = []
            for name, cls in vars(contracts).items():
                if (
                    isinstance(cls, type)
                    and issubclass(cls, contracts.Contract)
                    and (cls is not contracts.Contract)
                ):
                    atomic_json(target / f"{name}.schema.json", cls.model_json_schema())
                    names.append(name)
            atomic_json(target / "openapi.json", create_app(settings).openapi())
            result = {"schemas": names, "openapi": True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ValidationError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        # Errores de red no imprimen URLs, cabeceras ni cuerpos de terceros.
        print(
            json.dumps({"error": type(exc).__name__, "message": "Comprobación fallida"}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
