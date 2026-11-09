# Implementación de SCRUM-12

Comprobación del 5 de noviembre de 2026, zona America/Santiago. Ticket: [SCRUM-12](https://usach-team-nkit7ccq.atlassian.net/browse/SCRUM-12).

Se implementaron captura acotada de OpenAlex, reconstrucción de resúmenes, normalización, deduplicación por identidad/DOI, revisión en CSV y exportación offline. La selección queda preparada para SCRUM-26; aún no hay una generación publicada en Qdrant ni búsqueda funcional.

## Resultado real

| Medida | Resultado |
| --- | ---: |
| Registros observados en consultas | 310 |
| Registros únicos por OpenAlex ID | 305 |
| Apariciones repetidas eliminadas | 5 |
| Solicitudes reales / fallos | 8 / 0 |
| Registros en cuarentena / fusiones adicionales por DOI | 0 / 0 |
| Colección inicial | 100 únicos |
| Con resumen / solo metadatos | 90 / 10 |
| Piloto, subconjunto de la colección | 20 únicos: 18 con resumen y 2 solo metadatos |
| Excluidos / pendientes en CSV principal | 20 / 185 |
| Idiomas de la colección | 92 inglés / 8 español |

Ambas selecciones alcanzan el 90 % de resúmenes reconstruibles, superando la meta de 80 %. La muestra sin resumen es explícita. No se generaron resúmenes artificiales ni se extrajeron PDFs.

Configuración: [openalex.json](../config/openalex.json). Corte inclusivo 2020-01-01 a 2026-11-05. Seis consultas, cinco priorizando `has_abstract:true` y una con `false`; 50 resultados por página como máximo, hasta 310 observaciones, 40 solicitudes incluyendo reintentos, timeout 30 s, tres reintentos por petición y separación de 0,3 s. La captura duró aproximadamente 10,7 s. Un snapshot «completo» certifica el lote acotado, no cobertura exhaustiva del tema.

## Selección y límites del contenido

[CSV principal](../corpus/revision_corpus.csv) y [CSV del piloto](../corpus/revision_piloto.csv), con revisión realizada por Codex sobre contenido disponible. Cada incluido tiene un motivo y nota de evidencia; los diez sin resumen se identifican como selección por título. El piloto es una vista alternativa y no debe concatenarse con el CSV principal.

Tecnologías: 42 cámaras, 29 vestibles, 14 ambientales, 5 mixtas y 10 ND. Evidencia: 7 laboratorio, 5 simulada, 1 real_hogar y 87 ND. Los nombres de datasets no se usan para asumir condiciones experimentales. `real_hogar` corresponde a monitoreo en vivienda asistida TigerPlace, explicitado en la nota; FARSEEING conserva ND porque el resumen declara caídas reales sin precisar que fueran domiciliarias. La simulación de arquitectura FPGA se distingue de una validación clínica.

Se preservaron los subtipos fuente: 43 artículos, 41 trabajos de congreso, 9 tesis, 5 capítulos, 1 preprint y 1 otro. Estas etiquetas no acreditan revisión por pares. Se priorizaron métodos evaluados para la colección inicial; las revisiones de literatura permanecen candidatas de reserva, no se eliminaron por su tipo.

Hallazgos registrados:

- Resultados sobre derrumbes en minas, esquí, seguridad industrial e infestación agrícola se excluyeron del dominio acotado.
- Métodos declarados únicamente por umbrales, predicción de riesgo y casi-caídas no entran en la colección seleccionada.
- W4416940702 tiene un título de caídas y un resumen de firmas: permanece pendiente por incoherencia.
- W7217900637 comparte resumen con W3094311282 y W4394911199 es muy similar a W4389332502. Sin identidad/DOI común no se fusionaron; las posibles relaciones editoriales quedan pendientes.
- W4391153837 tiene resumen en coreano aunque pasó el filtro de idioma de OpenAlex; se excluyó y se conservó la anomalía en el CSV.
- «Resumen reconstruible» no garantiza calidad ni correspondencia temática: la revisión detecta estos casos y no acepta todos los resultados automáticamente.

## Artefactos y reproducción

Snapshot local: `data/snapshots/openalex_20261105_s12/`. Contiene `works.jsonl`, `manifest.json`, `requests.jsonl` y `quarantine.jsonl`. Los registros crudos ocupan aproximadamente 5,25 MB y se mantienen fuera de Git. La captura y su configuración no contienen la clave configurada, comprobado localmente.

Se versionan la [copia del manifiesto](../corpus/evidence/openalex_20261105_s12.manifest.json), [conteos y hashes](../corpus/evidence/scrum-12-checks.json), configuración y CSV. Conservar también el snapshot original en un respaldo: una nueva consulta al proveedor no garantiza la misma respuesta.

| Artefacto | SHA-256 |
| --- | --- |
| works.jsonl | `d788feb807b1cd7c9c783ab28b4ed73d0442c13cfb8ee96fcfb903508f4c3b77` |
| revision_corpus.csv | `18c25bcc4521405daaed3fe3801b20531c111007ac03817b4d375b30a2e92e7d` |
| revision_piloto.csv | `a50b4858c2f34528505aef7e60a29363cead136388d69fbf91a1fdfee15c320a` |
| Documentos normalizados de la colección | `25f77128137e43d99baef42ca3987a1025971b92c2e784bdabf6fce8bc8bf394` |
| Documentos normalizados del piloto | `ed4461ef0f6c86afc2b0533ed7c89f102ecff7cb3f3fa10caeb726cec7528d97` |

Desde la raíz de Asistente:

```powershell
.\.venv\Scripts\python.exe -m app.cli validate-review --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv
.\.venv\Scripts\python.exe -m app.cli validate-review --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_piloto.csv
.\.venv\Scripts\python.exe -m app.cli normalize --snapshot data/snapshots/openalex_20261105_s12 --csv corpus/revision_corpus.csv --output data/normalized/reproduccion_nueva
```

La salida debe ser nueva; ninguna exportación sobrescribe una anterior. La reproducción sobre el mismo snapshot y CSV produjo JSONL idéntico byte a byte para los 100 documentos y para los 20 del piloto, con los mismos IDs y orden. No requirió red, modelo de embeddings ni Qdrant. Las exportaciones comprobadas están en `data/normalized/s12_corpus_verified/` y `data/normalized/s12_pilot_verified/`.

## Verificación funcional

- **59 pruebas locales aprobadas**, 1 prueba de Qdrant omitida por no ser necesaria para el cambio de ingesta. La integración Qdrant ya se comprobó al cerrar SCRUM-10/11.
- Ruff sin errores y formato consistente. Contratos JSON Schema/OpenAPI regenerados, incluyendo FetchConfig y FetchSearch.
- Pruebas cubren cursor y fin de lote, límites, autenticación por cabecera, timeout de transporte, 429/Retry-After y errores 5xx, fallo tras una página, captura parcial, preservación de snapshots anteriores y hashes de archivos auxiliares.
- Verificación de resúmenes con palabras repetidas, huecos/posiciones inválidas, DOI canónico, campos desconocidos, cuarentena, conservación de procedencia, selección reproducible y bloqueo de decisiones/clasificaciones contradictorias.
- CSV principal y piloto validados contra IDs, contenido y hashes reales; IDs y DOI de incluidos únicos y piloto contenido en la colección.

No se ejecutó evaluación de calidad del recuperador ni RAGAS: siguen en Sprint 3. Fragmentación, embeddings, build y publicación corresponden a SCRUM-26.

## Referencias de implementación

Se contrastaron los filtros de fecha y combinaciones ES/EN con [OpenAlex: Filter](https://help.openalex.org/api/filtering/), y el cursor con el máximo soportado de 100 resultados por página con [OpenAlex: Page through Results](https://help.openalex.org/api/paging/). La configuración utiliza 50 por página. Los códigos de error se sanitizan; no se guardan cabeceras de autorización ni cuerpos de error del proveedor.
