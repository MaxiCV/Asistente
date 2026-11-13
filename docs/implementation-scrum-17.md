# SCRUM-17 · BM25 y búsqueda híbrida

**Actualización 12-11-2026:** incorporada selección real de patentes, incluido el caso
de Óscar Rojas/USACH. Ver [registro de integración](patent-corpus-2026-11-12.md).

Implementación del 10 de noviembre de 2026 sobre el incremento SCRUM-16.

## Comportamiento

`GET /api/v1/documents` acepta `mode=semantic|lexical|hybrid`; por defecto sigue
siendo semántico. La interfaz permite elegir modo y lo conserva junto con los
filtros y generación al cambiar de página.

- Semántico: E5 local, coseno y agrupación por documento.
- Léxico: vectores dispersos BM25 con IDF en Qdrant; no requiere E5 para consultar.
- Híbrido: recuperaciones densas y dispersas filtradas, fusión RRF nativa y
  agrupación por `document_id`, con un fragmento por documento.

La fusión recupera todos los fragmentos candidatos (máximo 10000), evitando
truncar grupos antes de paginar. Empates documentales ordenados por ID. BM25 se
añade a los mismos puntos: preserva IDs documentales y de fragmentos, sin cambiar
la configuración de fragmentación densa. Su configuración queda en el manifiesto.

`filtered_document_count` cuenta documentos que cumplen los filtros;
`matched_document_count` cuenta los recuperados. En modo léxico puede ser menor
o cero. `has_more` y la paginación de la UI usan el segundo conteo. La respuesta
indica el modo aplicado; los scores de distintos modos no son comparables.

## Construcción y compatibilidad

Servidor y cliente fijados en 1.20.0. La construcción BM25 comprueba la versión
antes de crear colecciones. Validación/publicación y consulta comprueban vector
disperso con modificador IDF; cada fragmento debe tener vector BM25 válido antes
de publicar. No se añade una base de datos relacional.

```powershell
.\.venv\Scripts\python.exe -m app.cli build nueva_generacion --bm25 --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv
# Cuando corresponda activar esta generación:
.\.venv\Scripts\python.exe -m app.cli publish nueva_generacion
```

Sin `--bm25` se conserva la construcción semántica. Los manifiestos antiguos son
compatibles; ausencia de `bm25` significa generación semántica. Pedir modo léxico
o híbrido sobre ellas devuelve 409 `search_mode_unavailable`, sin cambiar de modo
silenciosamente. La actualización exige una generación nueva.

El SDK usa `cloud_inference=True` para enviar objetos `Document` al servidor de
`QDRANT_URL`, incluido el Qdrant local. Ese nombre no implica usar Qdrant Cloud.
BM25 nativo no descarga pesos ni necesita FastEmbed; ingesta y consulta usan las
mismas opciones explícitas.

## Tokenización ES/EN

Modelo `qdrant/bm25`, tokenizador `word`, minúsculas, conservación de acentos,
sin stemming ni eliminación de stopwords, evitando aplicar reglas inglesas a todo
el corpus bilingüe. Parámetros: k=1.2, b=0.75, longitud media esperada 256
(constante del modelo, no media calculada sobre el corpus). IDF se calcula sobre
fragmentos en Qdrant. BM25 no traduce: `caída` y `fall` son términos distintos,
al igual que distintas formas flexionadas. La evaluación de calidad pertenece a S3.

Referencias oficiales:
[inferencia BM25](https://qdrant.tech/documentation/inference/inference-bm25/) y
[búsqueda híbrida, IDF y RRF](https://qdrant.tech/documentation/search-tuning/hybrid-search/).
Las opciones se verificaron también en `Bm25Config` del cliente Python instalado
y mediante el servidor local 1.20.0.

## Pruebas y pendientes

`test_hybrid.py` prueba BM25 real, modos, filtros, Unicode, consultas sin
coincidencias, agrupación, paginación, IDs/generación, modo léxico sin E5, modo
inválido y rechazo de vectores BM25 ausentes. Usa colecciones/alias aislados con
UUID, retirados al finalizar. Los vectores densos son sintéticos: no constituye
evaluación de pertinencia. La suite previa cubre compatibilidad y recuperación.

Pendientes: integración completa del corpus real de patentes (SCRUM-16), revisión
e integración del código. Las métricas de calidad se realizarán en Sprint 3.

Validación local: 137 pruebas aprobadas, incluidas las de integración contra
Qdrant 1.20.0; lint, formato, comprobación de diff y build del frontend aprobados.
Se construyó `s17_20261110_bm25` con 100 publicaciones, 90 resúmenes y 103 fragmentos,
usando E5 offline y BM25 nativo. Es una candidata validada, todavía no publicada;
los alias activos conservan la generación anterior. Para activarla, ejecutar
`python -m app.cli publish s17_20261110_bm25` con este código.

Se probaron consultas ES/EN en los tres modos sobre esa candidata con E5 real;
[evidencia funcional](evidence/scrum-17-smoke.json). Los 100 IDs documentales y
103 IDs de fragmentos coinciden con la generación activa anterior. Los alias no
cambiaron. Estos resultados comprueban ejecución, no relevancia ni calidad.
