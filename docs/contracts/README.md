# Contratos de corpus, generaciones y API

Fuente ejecutable: `backend/app/contracts.py`. Regenerar los archivos `*.schema.json` y `openapi.json` con `python -m app.cli export-schemas`. Los contratos rechazan campos desconocidos; identificadores de directorio aceptan solo letras minúsculas, números, guion y guion bajo (máximo 64 caracteres). No admiten rutas.

## Corpus y procedencia

`Document` contiene UUID estable, título, autores disponibles, fecha e idioma nullable, tipo/subtipo de publicación, DOI normalizado, URL original, resumen nullable y todas las identidades de OpenAlex/snapshot. `content_level=abstract` exige un resumen utilizable; `metadata` exige ausencia de resumen. Datos desconocidos se conservan como null o ND, nunca se infieren del título.

`Passage` contiene UUID, documento, posición, texto, número de tokens (incluido prefijo y tokens especiales), hash y copia de los campos de filtro. Las dimensiones y el límite de tokens proceden de `EmbeddingConfig`; `ChunkingConfig` registra el método y el solapamiento. La CLI implementa ventanas por tokens con título en cada fragmento, solapamiento de 32 tokens y rechazo explícito si no puede conservar el contenido dentro del presupuesto.

Fecha API/JSON: `YYYY-MM-DD`. Para el índice datetime de Qdrant, la ingesta serializa una fecha conocida como `YYYY-MM-DDT00:00:00Z`; las desconocidas quedan nulas y se excluyen al filtrar fechas.

## Archivos persistentes

| Ruta bajo data/ | Contrato | Regla |
| --- | --- | --- |
| snapshots/<id>/works.jsonl | Respuestas crudas de OpenAlex, una por línea | Inmutable tras completar; sin clave ni URL autenticada |
| snapshots/<id>/manifest.json | SnapshotManifest | Fechas/corte, búsquedas, conteos, hash y estado; completo requiere hash, fecha final y cero errores |
| snapshots/<id>/requests.jsonl | Registro de solicitudes sin cabeceras ni cuerpos de error | Consultas, filtros, cursor, intento, estado, IDs observados y motivo de cierre; hash en manifiesto |
| snapshots/<id>/quarantine.jsonl | Registros crudos inválidos y motivo | Sin ID canónico o título; conteo y hash en manifiesto |
| normalized/<salida>/documents.jsonl y report.json | Document y reporte de selección | Exportación offline, salida nueva; con `--csv` solo incluidos; no constituye generación publicada |
| generations/<g>/manifest.json | GenerationManifest | Pareja de nombres físicos, hashes de entradas/configuración, modelo, fragmentación y conteos validados |
| generations/<g>/published.json | PublicationReceipt | Primera publicación confirmada y hash del manifiesto; habilita lectura histórica, nunca sustituye a los alias activos |
| generations/<g>/build.json | Mediciones operativas | Carga, vectorización/escritura, presupuesto máximo y documentos fragmentados |
| runs/<id>.json | RunRecord | Último intento por operación; escritura temporal y reemplazo atómico |
| models/multilingual-e5-small/<revision>/ | Pesos y download.json | Revisión de 40 caracteres y SHA-256 de cada archivo; verificar antes de cargar |

No se guardan credenciales en estos archivos. El manifiesto de generación no actúa como un segundo puntero del índice activo.

`FetchConfig` y `FetchSearch` definen búsquedas, idioma, presencia de resumen, límites de registros/solicitudes, timeout y reintentos. El manifiesto de las capturas nuevas conserva esta configuración y exige hashes de solicitudes y cuarentena para declararse completo. Se mantiene lectura de manifiestos base de SCRUM-11 sin esos campos opcionales.

`fetch` escribe primero un manifiesto incompleto y JSONL temporal; finaliza el estado solo después de completar cada lote configurado y cerrar los archivos. Fallos conservan datos parciales con estado incompleto. Las capturas previas nunca se sobrescriben. Un límite de registros por consulta es un cierre normal de muestra; agotar el presupuesto de solicitudes antes de completar las consultas es un fallo.

La normalización conserva datos opcionales ausentes como null/lista vacía. DOI inválido pasa a null con aviso; fecha conocida fuera del corte, idioma no admitido e identidad/título inválidos van a cuarentena. Un resumen con posiciones duplicadas o huecos no es reconstruible. Deduplicación por ID de OpenAlex durante captura y por DOI canónico durante normalización; nunca por similitud de títulos. En un grupo se conserva el registro con resumen más largo (desempate por ID fuente) y todas las identidades; los originales permanecen en el snapshot.

## CSV

[revision_corpus.csv](../../corpus/revision_corpus.csv) contiene la selección real de SCRUM-12. `validate-review` comprueba esquema, enums, fechas, motivo/nota, duplicados, snapshot completo y hashes, pertenencia de IDs, coherencia de resumen y conflictos por identidad/DOI. Las filas de otros snapshots no participan. Decisiones distintas sobre el mismo DOI bloquean selección; una identidad sin fila cuenta como pendiente. Etiquetas no-ND contradictorias también bloquean; ND puede completarse con una etiqueta conocida del mismo documento.

`build` reutiliza `read_snapshot` y `select_documents`. `review_rows` cuenta filas del snapshot presente en el CSV; `pending_rows` indica decisiones pendientes y `unlisted_records` registros sin fila. Una fila pendiente no equivale a una inclusión revisada.

El CSV registra selección del corpus. Las consultas y los juicios de relevancia se crean en Sprint 3.

## API v1

| Ruta | Respuesta/contrato | Estado de este incremento |
| --- | --- | --- |
| GET /health | Proceso disponible, versión | Implementada |
| GET /ready | Qdrant, modelo cargado, corpus coherente, generación | Implementada; 503 esperado sin corpus |
| GET /documents | SearchParams → SearchResponse | Implementada: búsqueda densa exacta, filtros y agrupación por documento |
| GET /documents/{document_id} | UUID + generación → DocumentResponse | Implementada: detalle de la misma generación, 404 si el UUID no existe |
| GET /corpus | CorpusResponse | Implementada: manifiesto activo, cobertura, subtipos, primera publicación y último mantenimiento |

Todas las rutas llevan prefijo `/api/v1`. Consultas de 1–300 caracteres útiles, página desde 1, tamaño por defecto 20/máximo 100. Filtros: fecha inclusiva, tipo y subtipo. Fechas invertidas, entradas vacías e identificadores inválidos devuelven 422.

`SearchResponse` devuelve publicaciones únicas, puntuación de similitud (no probabilidad), paginación, número de documentos que cumplen filtros e `index_generation`. Se utiliza el máximo score entre fragmentos y desempate por UUID ascendente. El conteo incluye todos los documentos que cumplen los filtros: no hay un umbral de pertinencia. El navegador reenvía la generación en detalle y páginas y usa páginas de 10 resultados. Una nueva búsqueda o aplicación de filtros reinicia la versión y la página.

404 se reserva para documento ausente dentro de una generación válida; 409 para generación retirada o nunca publicada; 503 para dependencias o modelo incompatibles. No convertir un fallo en una lista vacía. `last_run` se calcula por fecha de inicio entre los registros; un fallo posterior no reemplaza los conteos del manifiesto publicado. `maintenance_status_unavailable` avisa si algún registro es ilegible. `published_at` conserva la primera publicación, también tras rollback; `last_run` informa el intento más reciente.

Cobertura obtiene `published_at` de un recibo cuya generación y hash del manifiesto estén validados. Un recibo presente ilegible o incompatible produce 503 `corpus_unavailable`; si no existe, devuelve `manifest.created_at` sin crear archivos. La fijación de la generación activa para búsqueda, detalle y disponibilidad sigue dependiendo de alias y manifiesto, no del recibo. La navegación histórica sí exige el recibo: ausente o ilegible devuelve 409; identidad o integridad incompatible devuelve 503.

## Publicación

La CLI es el único escritor y usa un bloqueo exclusivo. `documents` y `passages` apuntan a la misma generación y se cambian juntos; consultas usan los nombres físicos ya fijados. Una candidata sin recibo de publicación no puede consultarse como histórica. Ante timeout, la CLI vuelve a leer los alias antes de declarar éxito o fallo y nunca borra automáticamente una candidata. Una nueva dimensión/revisión implica nueva generación, nunca mezcla de vectores. `rollback` exige una versión previamente publicada compatible. El retiro manual de generaciones y los cambios de modelo requieren la API detenida; no existe limpieza automática.

La búsqueda agrupa todos los documentos filtrados para ordenar de forma determinista, con límite de 10.000 documentos. Ese límite protege esta implementación para un corpus pequeño; al crecer deberá reemplazarse por otra estrategia de paginación. La caché de 128 embeddings de consulta pertenece al proceso/modelo y no guarda resultados ni referencias a generaciones.

