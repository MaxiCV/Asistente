# Revisión documental — 8 de noviembre de 2026

## Resultado y alcance

La propuesta, el plan, los dos modelos Structurizr y las guías operativas quedan alineados con las decisiones del 4 de noviembre y el avance comprobado al 8 de noviembre. Había estados y referencias desactualizados; se corrigieron sin cambiar el alcance de los sprints ni el código de la aplicación.

La revisión contrasta documentos con código, contratos generados, CSV y snapshots, evidencias fechadas, servicios locales, Jira y documentación oficial. Los registros de implementación del 4, 5 y 7 de noviembre conservan sus resultados históricos; no se sustituyen sus cifras por las pruebas de hoy. No se reevalúa aquí la pertinencia de cada publicación ni la calidad de un chat todavía no implementado.

## Correcciones realizadas

| Hallazgo | Corrección |
| --- | --- |
| README y encabezado del plan terminaban en SCRUM-13; otra sección ya acreditaba SCRUM-14. | Estado consolidado: SCRUM-10 a SCRUM-14 finalizados, SCRUM-26 en curso y SCRUM-15 pendiente. |
| La propuesta describía una sola aplicación desplegable pese a tener API y CLI separadas. | Núcleo Python modular compartido por dos procesos, con responsabilidades diferenciadas. |
| El conteo anterior de tres contenedores podía confundirse con la arquitectura actual. | Cinco contenedores C4 en S1 y seis con el evaluador de S3. Compose ejecuta tres servicios. |
| La guía de arquitectura enlazaba al CSV vacío de la propuesta para construir el corpus. | Enlace al CSV real de `Asistente/corpus/`; el inicial queda identificado como esquema histórico. |
| El plan decía que no existían mediciones operativas y la guía del corpus hablaba de un `build` futuro. | Referencia a las mediciones de SCRUM-13 y al comando ya implementado. |
| El C4 atribuía al responsable la descarga directa de modelos y no mostraba el recibo de publicación. | Preparación mediante CLI, componente de descarga/verificación y escritura del recibo después de confirmar alias. Ambas copias del DSL permanecen idénticas. |
| El alcance de respaldo era poco preciso en la propuesta de arquitectura. | Solo generación activa y sus datos, procedencia, configuración y pesos; código, imágenes Docker e históricas se conservan aparte. |

## Comprobaciones realizadas hoy

| Comprobación | Resultado |
| --- | --- |
| Pruebas locales, `pytest -q -m "not integration"` | **95 aprobadas**, 14 de integración excluidas. Dos advertencias de Qdrant local indican diferencias de índices/búsqueda respecto del servidor. |
| Pruebas de servidor, `pytest -q -m integration` | **14 aprobadas** contra Qdrant **1.20.0**. Colecciones y alias de prueba aislados; los alias del corpus conservan `s13_20261105_v2`. |
| Frontend, `npm --prefix frontend run build` | TypeScript y Vite aprobados. |
| Contratos | **20 JSON Schema** coinciden con los modelos exportables. `openapi.json` coincide con la especificación generada por la API actual. |
| Dependencias | Versiones Python directas instaladas coinciden con las fijadas; PyTorch corresponde a la variante CPU. Dependencias directas del frontend coinciden con su lockfile. No se actualizaron paquetes. |
| Corpus y piloto | `validate-review` valida ambos CSV contra el snapshot y su hash, sin advertencias. Corpus: 100 incluidos, 90 resúmenes, 20 excluidos y 185 pendientes. Piloto: 20 incluidos y 18 resúmenes. |
| Servicio disponible | `/api/v1/ready` responde `ready`. `/api/v1/corpus` confirma 100 documentos, 90 resúmenes y 103 fragmentos en la generación publicada. |
| Structurizr | DSL validado con la herramienta oficial disponible, CLI v2025.11.09. Copias de propuesta y repositorio idénticas. Ocho vistas; seis contenedores en el modelo completo, uno reservado para S3. |
| Enlaces locales | Destinos de enlaces Markdown comprobados en propuesta, arquitectura y guías del repositorio; sin archivos faltantes. |
| LaTeX | Fuente actualizada en su archivo original. El compilador integrado no pudo iniciar por `CreateProcessAsUserW failed: 5 (Acceso denegado.)`. **No se confirma compilación ni maquetación del PDF**; es un fallo de arranque, no un diagnóstico de sintaxis TeX. |

No se repitió el ensayo completo de restauración ni la revisión visual de navegador: se conservaron las evidencias fechadas de SCRUM-14. La comprobación funcional no es una medición de relevancia.

## Vigencia de las herramientas externas

- **OpenAlex:** la documentación sigue ofreciendo US$1 diario de consumo gratuito por cuenta. Acepta `Authorization: Bearer` y requiere clave para paginación por cursor más allá de la primera página. El enfoque de captura con clave y búsquedas sobre el corpus local sigue siendo coherente. No se realizó una nueva captura ni se comprobó el saldo de la cuenta. [Precios](https://help.openalex.org/access/pricing/) y [autenticación](https://help.openalex.org/api/authentication/).
- **Qdrant:** admite operaciones de alias múltiples atómicas. El código añade la fijación de nombres físicos por petición para preservar coherencia entre lecturas. [Colecciones y alias](https://qdrant.tech/documentation/manage-data/collections/).
- **BM25:** Qdrant mantiene la ruta mediante vectores dispersos y ahora recomienda también el índice de texto con puntuación como ruta preferente. A1 conserva la solución dispersa aprobada; su implementación y eventual comparación de alternativas corresponden a S2. No se afirma que BM25 esté integrado. [Documentación actual](https://qdrant.tech/documentation/inference/inference-bm25/).
- **E5-small:** siguen siendo aplicables los vectores de 384 dimensiones, el límite de 512 tokens y los prefijos de consulta/documento. La configuración local conserva una revisión concreta. BGE-M3 y EmbeddingGemma 2 son candidatos, no sustituciones aprobadas. [E5](https://huggingface.co/intfloat/multilingual-e5-small) y [EmbeddingGemma 2](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2).
- **LlamaIndex:** el adaptador al recuperador existente sigue siendo una integración propuesta para S2. No es una dependencia instalada del Sprint 1. [Recuperadores](https://developers.llamaindex.ai/python/framework/module_guides/querying/retriever/).
- **RAGAS:** las métricas por IDs siguen documentadas y se distinguen de la evaluación de respuestas. Fijar versión y comprobar la API al implementar el arnés en S3; no se validaron resultados de relevancia. [Precisión](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/) y [recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/).
- **EPO OPS:** sigue siendo una fuente candidata para S2. La lectura de su documentación no acredita acceso, cuota o cobertura de una cuenta particular. [Servicio oficial](https://www.epo.org/en/searching-for-patents/data/web-services/ops).

## Pendientes y límites de la confirmación

- [SCRUM-26](https://usach-team-nkit7ccq.atlassian.net/browse/SCRUM-26) permanece en curso: falta el retiro controlado de generaciones. Build, publicación y rollback sí tienen implementación y pruebas.
- [SCRUM-15](https://usach-team-nkit7ccq.atlassian.net/browse/SCRUM-15) permanece por hacer. Esta revisión aporta documentación; no sustituye la aceptación del hito ni cambia estados de Jira.
- Patentes, BM25/híbrida y chat pertenecen a S2; consultas anotadas, RAGAS y evaluación de calidad pertenecen a S3.
- La entrega final continúa prevista hasta el **7 de enero de 2027**. Las fechas del plan no son fechas de ejecución efectiva.
- El repositorio presenta los archivos de implementación sin seguimiento Git. No se realizaron commits ni se acredita una reproducción desde un checkout limpio; queda por consolidar esa entrega versionada.
- Falta comprobar la compilación y maquetación del LaTeX cuando el compilador integrado pueda iniciarse.

La revisión confirma consistencia documental y las comprobaciones enumeradas, no ausencia absoluta de defectos ni finalización de todas las funciones del proyecto.
