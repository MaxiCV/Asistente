# Revisión del corpus

El CSV es la entrada versionada de selección del comando `build`, ya implementado. SCRUM-12 completó la selección real el 5 de noviembre de 2026 sobre `openalex_20261105_s12`, usada después para publicar `s13_20261105_v2`. Esta carpeta forma parte del repositorio de implementación.

- `revision_corpus.csv`: 305 filas; 100 incluidos (90 con resumen), 20 excluidos y 185 pendientes.
- `revision_piloto.csv`: subconjunto de 20 incluidos, 18 con resumen y 2 solo con título/metadatos. No concatenarlo con el principal: repetiría pares snapshot/ID.
- `evidence/`: copia del manifiesto y conteos/hashes comprobados. Los registros crudos se conservan en `data/snapshots/openalex_20261105_s12/`, fuera de Git.

La revisión fue realizada por Codex sobre títulos y resúmenes disponibles, con notas por registro. Las diez inclusiones sin resumen se justifican explícitamente por título. No se revisaron PDFs ni se verificó revisión por pares. Los pendientes no se incorporan; incluyen reservas para ampliar la colección y casos que requieren aclarar metadatos o metodología. Las revisiones de literatura no se excluyen por su tipo: se conservaron como candidatas de reserva.

Formato: UTF-8, separador coma, una fila por OpenAlex ID y snapshot. Citar con comillas dobles campos con comas o saltos de línea; duplicar comillas interiores. Fechas ISO `YYYY-MM-DD`. Mantener los identificadores como texto.

| Columna | Regla |
| --- | --- |
| `openalex_id` | URL canónica de OpenAlex de un registro real presente en el snapshot. |
| `snapshot_id` | Identificador del directorio/manifiesto de captura completo. |
| `decision` | `incluir`, `excluir` o `pendiente`. Solo `incluir` se indexa. |
| `motivo` | Justificación concreta de la decisión según alcance; obligatoria, incluso para pendientes. |
| `tecnologia` | `camara`, `vestible`, `ambiente`, `mixta` o `ND`. |
| `evidencia` | `laboratorio`, `simulada`, `real_hogar`, `mixta` o `ND`. Para laboratorio con caídas simuladas usar `simulada` y aclarar en la nota; combinaciones de modalidades de prueba usan `mixta`. |
| `tiene_resumen` | `si` o `no`, contrastado con el resumen reconstruido y utilizable, no solo con la presencia del campo fuente. |
| `fecha_revision` | Fecha real de revisión. |
| `nota_evidencia` | Qué contenido disponible respalda tecnología/entorno; si falta, explicar `ND`. No inferir evidencia clínica o domiciliaria a partir del título. |

## Selección

Incluir detección de caídas ocurridas, mediante ML/DL, aplicable al hogar; personas mayores como escenario principal. Admitir laboratorio y simulaciones con etiqueta explícita. Excluir prevención, riesgo o rehabilitación sin evaluación de detección. Trabajos mixtos pueden incluirse si evalúan detección. Mantener registros excluidos y pendientes para trazabilidad.

Meta del piloto: 20 únicos, al menos 16 con resumen. Meta inicial: 100 únicos, al menos 80 con resumen. Incluir una muestra real sin resumen de hasta el 20 %. La selección prioriza `has_abstract:true`; la proporción final se calcula después de deduplicar por identidad/DOI. Si no se alcanza, registrar el déficit y ajustar las búsquedas dentro del dominio.

## Contrato para la implementación de build

- Exigir snapshot completo y hash válido; filtrar el CSV por su `snapshot_id`.
- Rechazar duplicados de `(snapshot_id, openalex_id)`, IDs ausentes, enums/fechas inválidos y decisiones sin motivo. Las filas de otros snapshots no participan en esta construcción.
- Comprobar `tiene_resumen` contra el contenido reconstruido; un desacuerdo requiere revisión, no se ignora.
- Normalizar y deduplicar los incluidos. Si registros del mismo documento tienen decisiones contradictorias, resolver el conflicto antes de publicar; conservar todos los IDs y procedencias.
- Copiar tecnología y evidencia al payload como clasificación manual. Conservar el hash del CSV y conteos de incluidos/excluidos/pendientes en el manifiesto de generación.
- Indexar título cuando falte resumen y mostrar «Solo metadatos».

Este archivo documenta inclusión y exclusión del corpus. No contiene consultas ni etiquetas de relevancia del recuperador; ese conjunto y RAGAS pertenecen al Sprint 3. `validate-review` comprueba esquema, duplicados, snapshot/hash, pertenencia, resúmenes, normalización y conflictos de decisión/clasificación entre registros con el mismo DOI. `normalize --csv` exporta la selección offline. Construcción del índice y publicación corresponden a SCRUM-26.

La evidencia `real_hogar` de la colección corresponde a monitoreo en la residencia asistida TigerPlace; la nota distingue ese contexto de un domicilio particular. El estudio FARSEEING declara caídas reales pero no su ubicación domiciliaria en el resumen, por lo que conserva `ND`. No inferir entornos por nombres de datasets o por aplicaciones propuestas.

[Resultados y procedimiento reproducible](../docs/implementation-scrum-12.md).
