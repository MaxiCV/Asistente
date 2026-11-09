# Asistente de revisión de literatura

Buscador local para investigar detección de caídas en el hogar mediante ML/DL. Al **8 de noviembre de 2026** están implementados y finalizados en Jira **SCRUM-10 a SCRUM-14**, incluida la base de indexación de SCRUM-26. La web permite buscar en español e inglés, filtrar por fecha y tipo, leer fichas y copiar referencias. La colección publicada tiene 100 documentos únicos, 90 con resumen y 103 fragmentos. El piloto conserva 20 documentos, con 18 resúmenes. También están implementados el respaldo y la restauración de la generación activa. El retiro controlado de generaciones (SCRUM-26) y la aceptación del hito (SCRUM-15) siguen pendientes.

[Revisión documental y comprobaciones del 8 de noviembre](docs/revision-documentacion-2026-11-08.md). Los registros de cada incremento conservan sus cifras y fechas originales.

## Requisitos

- Docker Desktop con contenedores Linux.
- Python 3.12 (versión usada: 3.12.14) para la CLI.
- Node 24.21.0 para desarrollo fuera de Docker.
- Clave de OpenAlex en `.env`, solo para comprobación y captura.
- Espacio para imágenes, entorno virtual y pesos de E5-small.

Versiones directas fijadas en `pyproject.toml` y `frontend/package.json`; versiones transitivas y hashes en `uv.lock` y `frontend/package-lock.json`. Qdrant 1.20.0. PyTorch se instala desde su índice CPU. No se requieren LlamaIndex, RAGAS ni un LLM remoto en este incremento.

## Primer arranque en PowerShell

Desde la raíz del repositorio:

```powershell
.\scripts\bootstrap.ps1 -Python python
```

El script crea `.venv`, instala con el lockfile y crea directorios locales. Si Python no está en PATH, pasar su ruta mediante `-Python`. No modifica una configuración `.env` existente. En este equipo se utilizó el Python 3.12.14 incluido en el runtime de Codex.

Configurar `OPENALEX_API_KEY` en `.env`. Obtenerla en [OpenAlex](https://openalex.org/settings/api). La clave no se guarda en Git, snapshots, imágenes Docker ni en la web.

```powershell
.\.venv\Scripts\python.exe -m app.cli check-openalex
.\.venv\Scripts\python.exe -m app.cli prepare-model
.\.venv\Scripts\python.exe -m app.cli check-model
docker compose up -d --build
.\.venv\Scripts\python.exe -m app.cli check-env
```

`prepare-model` es el único comando que descarga pesos. Fija el hash de revisión y registra hashes SHA-256 de los archivos. `check-model` y la API usan rutas locales, `local_files_only=True` y modo offline; comprueban los archivos antes de cargar.

- Web: http://localhost:5173
- API y contrato interactivo: http://localhost:8000/docs
- Qdrant: http://localhost:6333/dashboard

La API puede tardar en arrancar por la primera carga del modelo. `/api/v1/health` responde 200 cuando el proceso está disponible. **`/api/v1/ready` responde 503 mientras no exista una generación publicada**, aunque Qdrant y el modelo ya funcionen. En este equipo está publicada `s13_20261105_v2`; un entorno nuevo necesita construir y publicar su colección con los comandos siguientes.

Los puertos de Compose se publican solo en localhost. La API monta `data/` en modo de solo lectura; la CLI es el escritor. El servidor web de Vite es para la demostración local.

## Desarrollo sin reconstruir imágenes

```powershell
docker compose up -d qdrant
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# En otra terminal:
npm --prefix frontend run dev -- --host 127.0.0.1
```

Detener antes los servicios `api` y `web` de Compose si ocupan esos puertos. Vite reenvía `/api` al backend; no requiere exponer credenciales al navegador.

## CLI y contratos

```powershell
.\.venv\Scripts\python.exe -m app.cli --help
.\.venv\Scripts\python.exe -m app.cli export-schemas
.\.venv\Scripts\python.exe -m app.cli create-collections mi_generacion
.\.venv\Scripts\python.exe -m app.cli validate-review --snapshot data/snapshots/mi_snapshot
```

Crear colecciones no publica datos ni cambia los alias. La CLI construye nuevas generaciones sin sobrescribir las anteriores:

```powershell
# Elegir un identificador nuevo para cada construcción.
.\.venv\Scripts\python.exe -m app.cli build mi_generacion --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv
.\.venv\Scripts\python.exe -m app.cli publish mi_generacion
# Solo una versión previamente publicada y compatible:
.\.venv\Scripts\python.exe -m app.cli rollback mi_generacion_anterior
```

`build` comprueba snapshot/CSV, fragmenta sin truncar, vectoriza offline y verifica escrituras antes de finalizar el manifiesto. `publish` cambia ambos alias en una operación. Las generaciones publicadas se conservan para paginación, detalle y rollback. No hay borrado automático: retirar versiones o cambiar de modelo requiere mantenimiento con la API detenida. Un bloqueo `data/index-writer.lock` tras un cierre abrupto debe revisarse comprobando que no exista otro escritor antes de retirarlo.

- [Contratos y propiedad de datos](docs/contracts/README.md).
- [Arquitectura C4 y decisiones](docs/architecture/README.md).
- [Reglas de revisión del corpus](corpus/README.md).
- [Registro de implementación y comprobaciones](docs/implementation-scrum-10-11.md).
- [Captura y selección real de SCRUM-12](docs/implementation-scrum-12.md).
- [Búsqueda, interfaz y mediciones de SCRUM-13](docs/implementation-scrum-13.md).
- [Pruebas y recuperación de SCRUM-14](docs/implementation-scrum-14.md).
- [Guion de demo y comandos de respaldo/restauración](docs/demo-local.md).

## Captura y selección del corpus

`fetch` necesita red y la clave configurada. Usa las búsquedas y límites versionados en `config/openalex.json`. El corte es explícito y cada intento exige un identificador nuevo: no sobrescribe snapshots anteriores. «Completo» significa que terminó el lote configurado, no que se descargó toda la literatura.

```powershell
# Ejemplo de nueva captura: ajustar identificador y corte a la fecha de ejecución.
.\.venv\Scripts\python.exe -m app.cli fetch mi_snapshot --cutoff 2026-11-05
.\.venv\Scripts\python.exe -m app.cli prepare-review --snapshot data/snapshots/mi_snapshot --csv corpus/mi_revision.csv --date 2026-11-05
.\.venv\Scripts\python.exe -m app.cli normalize --snapshot data/snapshots/mi_snapshot --output data/normalized/mi_captura
```

El último comando genera candidatos normalizados para revisar. Completar el CSV con decisiones, motivos y evidencia leída del título/resumen; nunca aprobar automáticamente todos los candidatos. `prepare-review` crea únicamente pendientes y exige un archivo nuevo.

La selección ya realizada se comprueba sin red:

```powershell
.\.venv\Scripts\python.exe -m app.cli validate-review --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv
.\.venv\Scripts\python.exe -m app.cli validate-review --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_piloto.csv
# Usar un directorio de salida nuevo en cada reproducción:
.\.venv\Scripts\python.exe -m app.cli normalize --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv --output data/normalized/mi_reproduccion
```

`normalize --csv` genera solo incluidos, resuelve identidades y rechaza contradicciones. Un snapshot incompleto o con hashes incorrectos no puede usarse. Los archivos crudos están en `data/` y fuera de Git: respaldarlos junto con los CSV. Reconsultar OpenAlex puede producir otros resultados; para reproducir exactamente se necesita el snapshot original. Ninguno de estos comandos publica datos en Qdrant.

## Comprobaciones

```powershell
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\ruff.exe format --check backend
.\.venv\Scripts\python.exe -m pytest -q
$env:QDRANT_TEST_URL = 'http://127.0.0.1:6333'
.\.venv\Scripts\python.exe -m pytest -q -m integration
npm --prefix frontend run build
# Medición HTTP funcional; iniciar una API nueva para medir consultas sin caché previa.
.\.venv\Scripts\python.exe scripts/check_search.py --output data/checks/search.json
```

Las pruebas de integración crean y eliminan solo colecciones y alias de prueba identificados por UUID. No modifican los alias `documents` y `passages`. Los datos sintéticos se usan únicamente en tests; los CSV de `corpus/` referencian registros reales de OpenAlex.

## Persistencia y credenciales

`docker compose stop` detiene servicios conservando volúmenes. `docker compose start` los reinicia. `docker compose down` conserva volúmenes; **añadir `-v` los elimina** y no forma parte del procedimiento normal.

El comando `backup --output <directorio_nuevo>` respalda la generación activa mediante snapshots nativos, sus alias, procedencia, configuración y pesos locales. `restore --backup <respaldo> --output <directorio_nuevo>` exige un Qdrant vacío. Seguir la [guía de recuperación](docs/demo-local.md); conservar también código e imágenes Docker. No basta con conservar el CSV para recuperar pesos y generaciones. Los alias de Qdrant son la autoridad de la generación activa.

`.env.example` contiene solo nombres y valores públicos. La comprobación OpenAlex usa un encabezado Authorization y devuelve únicamente estado y cuota permitida. Rotar una clave desde OpenAlex y reemplazarla en `.env`; reiniciar la CLI para leer el valor nuevo. La API no recibe esa clave en Compose.

