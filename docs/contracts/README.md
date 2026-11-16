# Contratos de corpus, generaciones y API

Fuente ejecutable: `backend/app/contracts.py`. Regenerar los archivos `*.schema.json` y `openapi.json` con `python -m app.cli export-schemas`. Los contratos rechazan campos desconocidos; identificadores de directorio aceptan solo letras minúsculas, números, guion y guion bajo (máximo 64 caracteres). No admiten rutas.

## Corpus y procedencia

Desde la integración del 12-11-2026, `Document` y `Passage` admiten `patent`.
La procedencia de patentes usa `PatentSourceIdentity` con identificador DOCDB,
snapshot, fecha y solicitantes; `authors` contiene los inventores disponibles.
La API permite `document_type=all|publication|patent`, conservando `publication`
como valor predeterminado. La UI consulta ambos tipos inicialmente.

SCRUM-17 añade `GenerationManifest.bm25` opcional: ausente/null conserva el modo
semántico anterior. `SearchParams.mode` acepta `semantic`, `lexical` o `hybrid`.
La respuesta incluye modo y `matched_document_count` para paginar coincidencias;
`filtered_document_count` sigue contando todos los documentos que cumplen filtros.
Léxico/híbrido en una generación sin BM25 devuelve 409 `search_mode_unavailable`.
Ver [tokenización y compatibilidad](../implementation-scrum-17.md).

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
| patents/snapshots/<id>/manifest.json | PatentSnapshotManifest | Estado, configuración, fechas y hashes; completo exige `patents.jsonl` y al menos un XML |
| patents/snapshots/<id>/page_*.xml y patents.jsonl | Respuesta OPS y bibliografía derivada | Inmutables; hashes verificados antes de seleccionar |
| generations/<g>/patent_selection.json | PatentSelectionFile | Selección inmutable de patentes publicadas; no se sustituye por la selección de trabajo |
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
| POST /chat | ChatRequest → ChatResponse | Implementada: recuperación, generación, citas y guardado confirmado |
| GET /chat/{conversation_id} | UUID, after, limit → ConversationResponse | Implementada: turnos ordenados, sin invocar encoder ni Gemini |

Todas las rutas llevan prefijo `/api/v1`. Búsqueda de 1–300 caracteres útiles, página desde 1, tamaño por defecto 20/máximo 100. Chat de 1–1000 caracteres, sujeto además al presupuesto del encoder local. `RetrievalParams` comparte modo y filtros sin imponer el máximo de búsqueda al chat. Filtros: fecha inclusiva, tipo y subtipo. Fechas invertidas, entradas vacías e identificadores inválidos devuelven 422.

`SearchResponse` devuelve documentos únicos, puntuación (similitud, BM25 o RRF según modo; nunca probabilidad), paginación e `index_generation`. Se utiliza el fragmento ganador y desempate por UUID ascendente. `filtered_document_count` cuenta todos los documentos que cumplen filtros; `matched_document_count` cuenta coincidencias del modo y determina la paginación. En léxico puede ser cero aunque el primero sea mayor que cero. El navegador conserva generación en detalle y páginas y usa páginas de 10 resultados.

404 se reserva para documento ausente dentro de una generación válida; 409 para generación retirada o nunca publicada; 503 para dependencias o modelo incompatibles. No convertir un fallo en una lista vacía. `last_run` se calcula por fecha de inicio entre los registros; un fallo posterior no reemplaza los conteos del manifiesto publicado. `maintenance_status_unavailable` avisa si algún registro es ilegible. `published_at` conserva la primera publicación, también tras rollback; `last_run` informa el intento más reciente.

Cobertura obtiene `published_at` de un recibo cuya generación y hash del manifiesto estén validados. Un recibo presente ilegible o incompatible produce 503 `corpus_unavailable`; si no existe, devuelve `manifest.created_at` sin crear archivos. La fijación de la generación activa para búsqueda, detalle y disponibilidad sigue dependiendo de alias y manifiesto, no del recibo. La navegación histórica sí exige el recibo: ausente o ilegible devuelve 409; identidad o integridad incompatible devuelve 503.

## Publicación

La CLI es el único escritor del corpus y usa un bloqueo exclusivo. `documents` y `passages` apuntan a la misma generación y se cambian juntos; consultas usan los nombres físicos ya fijados. Una candidata sin recibo de publicación no puede consultarse como histórica. Ante timeout, la CLI vuelve a leer los alias antes de declarar éxito o fallo y nunca borra automáticamente una candidata. Una nueva dimensión/revisión implica nueva generación, nunca mezcla de vectores. `rollback` exige una versión previamente publicada compatible. El retiro manual de generaciones y los cambios de modelo requieren la API detenida; no existe limpieza automática.

La búsqueda agrupa todos los documentos filtrados para ordenar de forma determinista, con límite de 10.000 documentos. Ese límite protege esta implementación para un corpus pequeño; al crecer deberá reemplazarse por otra estrategia de paginación. La caché de 128 embeddings de consulta pertenece al proceso/modelo y no guarda resultados ni referencias a generaciones.

## Conversación e historial

`ChatRequest` exige un UUID `request_id`, pregunta y filtros opcionales; `document_type` predetermina `all`. Una conversación nueva fija la generación activa o la solicitada. La continuación conserva esa versión aunque se publique otra. Su respuesta incluye estado, nivel de evidencia, modelo, contexto recuperado (IDs, hash, score, nivel y marca de citado) y citas con título y procedencia. Los IDs citados deben pertenecer al contexto; marcadores y lista de citas coinciden exactamente. Se admiten grupos `[1, 2]`, normalizados a `[1][2]`. Citas inválidas descartan todo el texto y producen evidencia insuficiente. La pertenencia de IDs no evalúa fidelidad semántica.

`ChatTurn` conserva petición normalizada, hash de petición, respuesta y motivo de rechazo estructural, sin el texto descartado. La API guarda cada turno en `chat_turns`, punto con ID `request_id`, sin vectores ni alias. Payload: `conversation_id`, `turn_index`, `turn`; índices keyword e integer respectivamente. La colección se crea al primer guardado, no al consultar ni al comprobar disponibilidad. Reconstruir o publicar corpus no la modifica y su respaldo no la incluye.

Un único proceso API bloquea solicitud y luego conversación durante lectura, generación y guardado. Repetir UUID y cuerpo devuelve el turno guardado; cambiar el cuerpo produce 409 `request_id_conflict`. Sin conversación inicial se deriva un UUID5 estable de la solicitud. Se confirma persistencia antes del 200; un fallo ambiguo se reconcilia reintentando el mismo envío. No se garantiza ejecutar el proveedor una sola vez si el proceso cae antes de guardar.

GET devuelve hasta `limit` turnos (20 por defecto, máximo 100), ordenados por `turn_index`; `next_cursor` se pasa como `after`. Puede leer conversaciones de una generación retirada, aunque abrir fichas o continuar esa conversación devuelva 409. Los límites de 30 s proveedor, 60 s operación y 75 s navegador son independientes del timeout de búsqueda.

| HTTP / código | Situación |
| --- | --- |
| 404 `conversation_not_found` | Hilo inexistente |
| 409 `request_id_conflict`, `conversation_generation_mismatch` | Clave reutilizada con otro cuerpo o cambio de generación del hilo |
| 409 `generation_retired`, `search_mode_unavailable` | Generación ausente/no publicada o modo sin BM25 |
| 422 `query_not_encodable` | Presupuesto de tokens excedido; otras validaciones usan `RequestValidationResponse` de FastAPI |
| 503 `llm_unavailable` | Clave ausente o proveedor no inicializable |
| 502 `llm_failed` | Timeout, rechazo remoto o respuesta estructurada inválida |
| 503 `chat_history_unavailable` | Lectura, escritura o integridad de historial fallida |
| 503 `model_unavailable`, `corpus_unavailable`, `dependency_unavailable` | Fallo del recuperador, sin convertirlo en contexto vacío |

OpenAPI documenta ambos formatos de 422. `/ready.chat` es un indicador local de clave configurada fuera de `checks`: no consulta Gemini y no cambia la disponibilidad del buscador. Configuración, datos enviados al proveedor y límites operativos: [SCRUM-18](../implementation-scrum-18.md).

