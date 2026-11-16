# SCRUM-18 · Conversación con fuentes

Implementación del 15 de noviembre de 2026 sobre `feat/scrum-18-rag-chat`, por Codex sin consumir cuota Claude. Precede el commit `1d74cdc` con las [correcciones de SCRUM-16/17](revision-scrum-16-17-2026-11-14.md). El trabajo local no cambia estados de Jira ni publica una generación nueva.

## Comportamiento implementado

- `POST /api/v1/chat` recupera hasta cinco fragmentos, uno por documento, y genera una respuesta en español con Gemini 3.5 Flash-Lite. El modo inicial es híbrido; los filtros explícitos del buscador se reutilizan al entrar al chat.
- `CorpusRetriever`, adaptador `BaseRetriever` de LlamaIndex, reutiliza recuperación densa/BM25/RRF, nombres físicos fijados y fragmentos ganadores existentes. Los nodos conservan `passage_id`; no se construye otro índice ni se inicializan embeddings implícitos.
- Las citas conservan documento, fragmento, título, fecha y DOI o identificador de patente. Cada marcador debe aparecer en la lista de fuentes y en el contexto. Grupos como `[1, 2]` se comprueban completos y se normalizan a `[1][2]`; rangos y referencias inválidas descartan la respuesta completa. No se conserva la afirmación eliminando solo su marcador.
- `evidence_level` se calcula sobre las fuentes citadas: `abstract`, `metadata_only` o `mixed`. Sin respaldo válido se devuelve `insufficient_evidence` con nivel `none`. Sin fragmentos no se construye ni invoca Gemini.
- El prompt limita afirmaciones a contenido disponible: títulos/metadatos no acreditan métodos ni resultados, resúmenes no son texto completo y solicitudes de patente no demuestran concesión o vigencia. Estas reglas orientan la generación; las pruebas estructurales no garantizan fidelidad semántica.
- Hasta cuatro pares completos de historial reciente acompañan la pregunta, sin marcadores históricos. La entrada está acotada a 40.000 caracteres y la salida a 2.048 tokens. Se recupera con la pregunta actual; reformular seguimientos queda para S3.
- La interfaz incorpora hilo, fuentes clicables que abren la ficha existente, nivel de evidencia, modo/filtros por turno, estados de carga/error, reintento y nueva conversación. Renderiza texto escapado, conserva foco visible y usa `aria-live`. Los estados tardíos de un hilo abandonado no repueblan el nuevo.

## Historial, identidad y operación

Qdrant es la única base de datos. `chat_turns` es una colección separada, sin vectores ni alias, creada al primer guardado. Un punto por `request_id` contiene petición normalizada y su SHA-256, respuesta con contexto/citas, número de turno y motivo de rechazo estructural cuando corresponde. Los índices `conversation_id` y `turn_index` permiten recuperar el hilo en orden y paginarlo con `after`/`limit`.

El primer `conversation_id` se deriva mediante UUID5 de la solicitud. Mismo ID y mismo cuerpo devuelve el turno guardado; cuerpo diferente produce 409 `request_id_conflict`. El guardado debe confirmarse antes del 200. Si se pierde la confirmación, reintentar el mismo cuerpo permite reconciliarlo. Una caída antes del guardado puede repetir la inferencia remota: no se promete ejecución exactamente una vez del proveedor.

**Solo se admite un proceso API (`--workers 1`) y una réplica.** Los bloqueos en memoria se adquieren en orden solicitud → conversación y cubren lectura, asignación de turno, generación y persistencia. Deshabilitar doble envío en la web complementa esos bloqueos. Una operación tiene 60 s de límite total; Gemini, 30 s sin reintentos automáticos; el navegador, 75 s. Tras cancelar, la recuperación en un hilo puede terminar su lectura, pero no genera ni guarda un turno posteriormente.

Una conversación fija la generación de su primer turno. Publicar otra colección no la cambia ni toca su historial. Cambiarla explícitamente produce `conversation_generation_mismatch`; si se retira, nuevas preguntas/fichas producen `generation_retired`, pero GET puede mostrar los turnos guardados.

La pestaña conserva conversación, generación y cuerpo pendiente en `sessionStorage`; al recargar usa `GET /api/v1/chat/{conversation_id}`. «Nueva conversación» no borra el historial previo. Los respaldos de corpus no incluyen `chat_turns`; conservar el volumen Qdrant es necesario para preservar conversaciones. No hay catálogo de sesiones ni borrado desde UI en este incremento.

## Configuración y proveedor

`config/chat.json` fija proveedor `google-genai` y modelo `gemini-3.5-flash-lite`. `GEMINI_API_KEY` tiene prioridad sobre el alias `GOOGLE_API_KEY`. Compose recibe únicamente esa credencial de chat y mantiene `data/` de solo lectura. Las claves de captura OpenAlex/EPO no se envían a la web ni se requieren para conversar con un corpus existente.

La llamada externa transmite pregunta, fragmentos con metadatos/procedencia y hasta cuatro turnos recientes. Las conversaciones se guardan en Qdrant local. Sin clave, el chat con contexto devuelve 503 `llm_unavailable` y el buscador sigue disponible. `/ready.chat` solo informa si existe configuración local de clave; no prueba cuota o acceso remoto y está fuera de los criterios de disponibilidad del buscador.

Dependencias directas fijadas: `llama-index-core==0.14.26`, `llama-index-llms-google-genai==0.12.0`, `google-genai==2.34.0`. No se instala el metapaquete `llama-index`. La primera comprobación real detectó que el transporte `response_schema` rechaza `additionalProperties` de los contratos estrictos; el adaptador usa un modelo compatible con el proveedor y valida después contra `LlmAnswer`. La regresión verifica el cuerpo HTTP con transporte simulado, sin invocar Gemini.

Los fallos remotos, cuota, acceso, JSON inválido y timeouts se exponen como errores controlados, sin texto crudo del SDK ni secretos. Corpus, proveedor e historial tienen códigos distintos. OpenAPI y [contratos](contracts/README.md) documentan ambos formatos de 422, errores 409 y contratos del chat. También se centralizaron/exportaron `PatentSelection`, `PatentSelectionFile` y `PatentSnapshotManifest` (A-06).

## Comprobaciones

Resultado de cierre: **173 pruebas unitarias, 34 de integración y seis recorridos Playwright aprobados**; Ruff y compilación TypeScript/Vite correctos. Contratos regenerados y comprobados sin deriva. [Registro de verificaciones](evidence/scrum-18-checks.json). Qdrant local emite avisos esperados sobre índices sin efecto en memoria; BM25, snapshots y restauración se comprueban contra el servidor real.

Las suites automáticas usan proveedores falsos y transporte HTTP simulado. La importación de API y exportación OpenAPI se comprueban sin conexiones de red. La integración utiliza Qdrant 1.20.0, colecciones/alias con UUID y un segundo servidor vacío en 6335 para restauración; no altera alias `documents`/`passages` del usuario.

```powershell
.\.venv\Scripts\python.exe -m ruff check backend scripts/check_chat.py
.\.venv\Scripts\python.exe -m ruff format --check backend scripts/check_chat.py
.\.venv\Scripts\python.exe -m pytest -q -m 'not integration'
$env:QDRANT_TEST_URL='http://127.0.0.1:6333'
$env:QDRANT_RESTORE_TEST_URL='http://127.0.0.1:6335'
.\.venv\Scripts\python.exe -m pytest -q -m integration
.\.venv\Scripts\python.exe -m app.cli export-schemas
npm --prefix frontend run build
# En este equipo se utiliza Edge instalado; CI instala Chromium.
$env:PLAYWRIGHT_CHANNEL='msedge'
npm --prefix frontend run test:e2e
```

Cobertura: fragmento ganador y padre, corrupción de fragmentos, filtros y generaciones, preguntas de más de 300 caracteres, ambas formas de 422, sin clave/sin contexto, error/timeout remoto, citas inválidas/agrupadas, niveles de evidencia, límites de historial, paginación, idempotencia concurrente, cuerpo conflictivo, escritura ambigua, persistencia, esquema sin vectores/alias y publicación/retirada del corpus sin perder historial. Los fixtures sintéticos pueden empatar en puntuación; se verifica el ganador de la misma consulta, sin asumir orden estable entre consultas independientes.

Seis recorridos Playwright cubren POST/citas/recarga/seguimiento/nuevo hilo, reintento con cuerpo idéntico ante fallo de red o respuesta vacía del proxy, respuesta tardía abandonada, limpieza de tipo documental/vacío léxico, recuperación semántica ante modo incompatible y fechas corregibles en móvil sin desborde. CI incorpora estos recorridos y conserva el control de deriva de esquemas. La revisión de arranque del 16 de noviembre confirmó recuperación del historial tras reiniciar y sustituyó el error de parseo crudo por un mensaje recuperable.

Comprobación con proveedor real: [scrum-18-chat.json](evidence/scrum-18-chat.json), seis casos funcionales válidos sobre `s17_20261112_patents`, sin cambiar la generación activa. Cuatro respuestas citadas (sensores ES, técnicas EN, seguimiento y WAND), dos estados de evidencia insuficiente (limitaciones ES y receta fuera de dominio). WAND cita `US.2016189026.A1`. `quality_evaluated=false`: se verifican contrato y pertenencia de citas, no relevancia ni exactitud de afirmaciones.

El recorrido real de navegador se registra en [scrum-18-browser.json](evidence/scrum-18-browser.json), con capturas de [escritorio](evidence/scrum-18-desktop.png), [móvil](evidence/scrum-18-mobile.png) y [ficha citada](evidence/scrum-18-citation.png).

## Alcance pendiente

A-01/A-02/A-03 están atendidos en el commit previo. A-06 y A-07 se atienden aquí mediante contratos, descripción de API, crédito OpenAlex/EPO y documentación actualizada. De A-08 se cubrieron errores HTTP y deriva de esquemas; quedan teardown ante caída de Qdrant y casos de rechazo de idioma.

Se mantienen para trabajo posterior A-04 (comprobación de compatibilidad BM25 fuera de build y disponibilidad léxica sin encoder), A-05 (reintentos OPS, `search=black:0`, saltos de línea y deduplicación XML), A-09 (propiedades RRF por fragmento y límites Prefetch), reformulación de seguimientos y evaluación de relevancia/fidelidad/RAGAS en S3. Una auditoría independiente es opcional; esta entrega se verificó mediante autorrevisión y pruebas, sin Claude.
