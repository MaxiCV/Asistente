# Incorporación de patentes · 12 de noviembre de 2026

Credenciales de aplicación EPO OPS comprobadas mediante OAuth y búsqueda real
(HTTP 200). Se admiten los nombres `EPO_CONSUMER_KEY`/`EPO_CONSUMER_SECRET` usados
en este entorno y los nombres `EPO_OPS_CONSUMER_KEY`/`EPO_OPS_CONSUMER_SECRET` de
la plantilla. Los valores no se registran ni se versionan.

## Captura y selección

Dos snapshots completos conservados en `data/patents/snapshots/`:

- `ops_20261112_falls`: 25 registros de 2222 resultados reportados por
  `ta="fall detection"`.
- `ops_20261112_rojas`: 25 registros de 40 resultados reportados por
  `in=rojas and in=oscar`. Esta búsqueda descubre homónimos; no los atribuye al profesor.

El 12 de noviembre local corresponde al 13 de noviembre UTC en los manifiestos.
Las capturas no son exhaustivas. Sus páginas XML y JSONL normalizados tienen
hashes SHA-256; no se modifican al enriquecer los datos para indexación.

Se revisaron títulos y resúmenes y se eligieron seis registros explícitamente en
[`corpus/patent_selection.json`](../corpus/patent_selection.json), con motivo y
alcance por registro. Los demás candidatos no se incorporan al índice.

| Publicación DOCDB | Motivo |
| --- | --- |
| US.20260255015.A1 | Radar mmWave y aprendizaje automático en habitación |
| CN.122531182.A | Smartwatch, red neuronal ligera y confirmación de caídas |
| CN.122511023.A | Postura, red temporal y seguridad de mayores en el hogar |
| CN.122531109.A | Vídeo multimodal y clasificador de caídas |
| WO.2026226852.A1 | Fusión de sensores en espacios de cuidado; contexto tecnológico |
| US.2016189026.A1 | Caso de Óscar Rojas solicitado por el usuario, fuera del tema de caídas |

## Identificación del caso USACH

**Running Time Prediction Algorithm for WAND Queries**, publicación
**US20160189026A1**, fecha 2016-06-30. OPS usa la forma DOCDB sin cero de relleno
`US.2016189026.A1`. Inventores: Mauricio Marín, Verónica Gil-Costa y Óscar Rojas.
Solicitante: Universidad de Santiago de Chile. Estos datos se verificaron en el
XML autenticado de OPS. Se trata de una publicación de solicitud A1; no se afirma
que sea una patente concedida ni se deduce vigencia legal del registro.

La identificación concuerda con el perfil académico facilitado por el usuario y
el [perfil del DMCC USACH](https://www.dmcc.usach.cl/personas/oscar-rojas-diaz/).
También se cotejó la [ficha de publicación](https://patents.google.com/patent/US20160189026A1/en).

## Integración

`build --patent-selection corpus/patent_selection.json --bm25` combina la selección
con el corpus científico. Valida estado completo, hashes, conteos, duplicados e
idiomas ES/EN. Conserva inventores, solicitantes, fecha, identificador y snapshot.
Relee el XML original para incorporar nombres sin modificar la captura histórica.
Las fechas de procedencia de esta normalización corresponden al cierre de la captura.

Los documentos de patente tienen UUID estable a partir de su identificador DOCDB;
los fragmentos conservan `document_type=patent`. La API admite `document_type=all`,
`publication` o `patent`; por compatibilidad el valor API por defecto sigue siendo
`publication`. La UI envía `all` inicialmente y ofrece filtro de documentos.
La ficha muestra EPO OPS, inventores y solicitante; su enlace público abre Espacenet.

El manifiesto de generación registra el hash de la selección y conserva una copia.
Respaldo y restauración incluyen la selección y los snapshots OPS referenciados.
Los datos crudos permanecen fuera de Git y deben conservarse mediante respaldo.

## Comprobaciones y activación

Publicada localmente `s17_20261112_patents`: 106 documentos, 96 resúmenes y
109 fragmentos. API y web reconstruidas. La generación anterior sigue conservada.
La suite pasó 145 pruebas con Qdrant real; adicionalmente pasó la prueba de
normalización de inventores/solicitantes. Lint, formato y build web aprobados.
Se volvieron a ejecutar las nueve pruebas de recuperación tras ampliar su validación.

Comprobación HTTP con la API local: las seis patentes están disponibles; `WAND`
recupera la solicitud de Óscar Rojas en los tres modos, y su ficha muestra a USACH
como solicitante. Evidencia: [capturas y selección](evidence/patents-2026-11-12.json)
y [consultas HTTP](evidence/patents-http-2026-11-12.json). No constituye evaluación
de relevancia ni análisis de vigencia legal.

Respaldo local creado en `data/backups/s17_20261112_patents` (39 archivos),
incluidos ambos snapshots OPS y la selección de patentes. No contiene credenciales.
