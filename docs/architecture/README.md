# Arquitectura de los incrementos SCRUM-10 a SCRUM-18

El [modelo C4](workspace.dsl) conserva la arquitectura aprobada: web React/TypeScript, API FastAPI, CLI Python separada, Qdrant como única base de datos y archivos persistentes. Patentes, BM25/RRF y chat de Sprint 2 están implementados; la evaluación de Sprint 3 sigue pendiente.

Revisión del 15 de noviembre de 2026: cinco contenedores C4 implementados y un sexto futuro para evaluación offline. Compose ejecuta tres servicios; API y CLI son procesos distintos con módulos compartidos. [Comprobaciones y pendientes del chat](../implementation-scrum-18.md).

## Límites de responsabilidad

| Proceso | Lee | Escribe |
| --- | --- | --- |
| Web | API local; conserva generación en búsqueda y conversación | Estado y envío pendiente en sessionStorage |
| API | Corpus publicado, pesos e historial; Gemini para respuestas | Solo `chat_turns`, separado del corpus |
| CLI | OpenAlex/EPO OPS durante captura; snapshots y selecciones durante construcción | Archivos, colecciones candidatas y publicación/rollback por alias |
| Evaluador futuro | Corpus congelado y API | Anotaciones e informes desde Sprint 3 |

API y CLI comparten módulos de contratos, configuración, identidad y generaciones. No hay workers, colas, almacenamiento SQL ni segundo puntero mutable del índice activo.

La API se ejecuta con un único proceso. `CorpusRetriever` implementa `BaseRetriever` de LlamaIndex sobre los grupos existentes y sus fragmentos ganadores; usa sus mismos IDs y no construye otro índice ni inicializa embeddings implícitos. Gemini se crea solo cuando hay contexto. El historial queda fijado a la generación del primer turno y almacena IDs del contexto recuperado y de las fuentes citadas. Los bloqueos por solicitud y conversación permiten reintentos y serialización dentro de ese proceso.

## Evidencia de publicación

El módulo `app.catalog.generations` concentra la relación entre generación, manifiesto, modelo y recibo. Su interfaz distingue dos lecturas: `pin_generation` fija la generación desde los alias o una petición histórica; `read_generation` comprueba la evidencia local sin resolver alias ni escribir. Esta última devuelve el manifiesto y un recibo validado cuando existe, con `published_at` resuelto al recibo o a la fecha del manifiesto. Publicación, recuperación y cobertura comparten esa implementación; sus consumidores no interpretan por separado la identidad ni el hash del recibo.

La política activa sigue dependiendo de alias y manifiesto, sin exigir recibo. La histórica y los respaldos sí lo exigen; rollback también. `record_publication` es la operación explícita del escritor, bajo bloqueo y después de confirmar alias: conserva un recibo existente y su fecha, o crea el que falta. También permite registrar la activa anterior antes de sustituirla. Ninguna lectura repara archivos.

La cobertura rechaza recibos presentes incompatibles con 503 `corpus_unavailable`; si falta el recibo, conserva el fallback a `manifest.created_at`. Esta comprobación adicional no condiciona búsqueda ni disponibilidad de la activa a la presencia de un recibo. El [glosario](../../GLOSSARY.md) define los términos de generación y publicación.

## Decisiones implementadas

- Contratos Pydantic estrictos, exportados a JSON Schema y OpenAPI.
- Identidad documental UUIDv5 basada en DOI normalizado o ID de fuente; un fragmento incorpora documento, posición y hashes de texto/configuración.
- Colecciones `documents_<g>` sin vectores y `passages_<g>` con vector nombrado `dense`. Índices de payload para ID, fecha y tipos.
- La creación de una candidata es repetible y rechaza colecciones referidas por cualquier alias.
- El lector obtiene todos los alias una vez, valida pareja y manifiesto y devuelve nombres físicos fijados para toda la petición.
- Pesos E5-small por revisión y hashes locales, carga offline, control de longitud antes de vectorizar.
- Configuración de conexión y secretos fuera del código; API sin clave OpenAlex en Docker.
- Captura OpenAlex acotada e inmutable, con manifiesto, consultas, cuarentena y hashes; normalización y selección offline desde snapshot y CSV.
- Selección real de 100 documentos (90 resúmenes), con piloto de 20 (18 resúmenes). Publicados 103 fragmentos en `s13_20261105_v2`. [Evidencia de búsqueda e indexación](../implementation-scrum-13.md).
- Recuperación densa exacta agrupada por documento, con máximo score de fragmento y desempate por UUID. Filtros aplicados a catálogo y fragmentos, paginación estable para el corpus pequeño.
- Patentes EPO OPS y selección revisada incorporadas a `s17_20261112_patents`: 106 documentos y 109 fragmentos. BM25 y fusión RRF habilitadas por manifiesto, conservando lectura de generaciones solo densas.
- Síntesis Gemini 3.5 Flash-Lite, validación de pertenencia de citas y niveles de evidencia. Persistencia confirmada en colección Qdrant sin vectores ni alias; creación perezosa, clave estable por envío y paginación del historial.
- Respaldo y restauración de la generación activa, incluidos pesos y procedencia, con ensayo aislado registrado en [SCRUM-14](../implementation-scrum-14.md). El código, las imágenes Docker y las generaciones históricas requieren conservación separada.

## Protocolo definido para SCRUM-26

1. `fetch` ya captura JSONL, conteos, filtros y hashes en SCRUM-12. Una captura incompleta nunca es elegible.
2. `build` reutiliza la lectura validada del snapshot y la selección normalizada (`select_documents`), prepara fragmentos y escribe nuevas colecciones.
3. Verifica conteos, vínculos, vectores, índices y contenido; finaliza el manifiesto inmutable.
4. `publish` cambia ambos alias en una sola operación. Ante timeout consulta los alias antes de decidir si repetir. Una pareja mezclada bloquea la resolución del corpus activo.
5. Cada petición fija nombres físicos; la navegación conserva `index_generation`. Una generación retirada devuelve 409.
6. Cambios de modelo y limpieza con API detenida. Conservar activa y anterior; `rollback` restaura los dos alias y exige compatibilidad con la configuración del modelo cargado. El comando de retiro controlado sigue pendiente en SCRUM-26.

`published.json` registra una publicación confirmada y el hash del manifiesto: una candidata con manifiesto no basta para autorizar navegación histórica. Los alias siguen siendo la única autoridad del índice activo. La resolución histórica exige recibo válido, manifiesto compatible y ambas colecciones presentes. La API solo lee el corpus; su única escritura es el historial separado. Publicación, reconstrucción y respaldo de corpus no incluyen `chat_turns`.

## Siguientes sprints

Sprint 3: consultas anotadas, métricas RAGAS, relevancia, revisión de respuestas y reformulación de seguimientos. La elección de embeddings prioriza relevancia y velocidad local; E5 es provisional, BGE-M3 y EmbeddingGemma 2 son candidatos. La validación estructural de citas de S2 no sustituye esta evaluación.

