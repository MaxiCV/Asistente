# SCRUM-14 — pruebas y demo local

Completado y verificado el **7 de noviembre de 2026**, antes de la ventana planificada del 20 al 25 de noviembre. [Guía reproducible](demo-local.md).

## Evidencia de aceptación

| Criterio | Resultado verificado |
| --- | --- |
| Fixtures y fallos | 70 pruebas locales aprobadas; seis pruebas adicionales del respaldo aprobadas. |
| Qdrant real fijado | 10 pruebas de integración aprobadas con Qdrant 1.20.0, colecciones y alias de prueba aislados por UUID. |
| Interrupciones | Ctrl+C simulado durante la segunda página de fetch y durante embeddings del build: captura incompleta/candidata fallida; corpus activo preservado y bloqueo liberado. |
| Publicación concurrente | Cambio real de alias dentro de una búsqueda en curso: la respuesta usa la generación física fijada al empezar. Timeouts antes y después del commit y rollback comprobados. |
| Modelo real del piloto | E5-small local fijado: 20 documentos, 18 resúmenes, 22 fragmentos. Publicación, búsquedas ES/EN con 20 IDs únicos y rollback a 100 documentos. |
| Recuperación | Restaurados 100 documentos y 103 fragmentos; igualdad exacta de todos los IDs, payloads y vectores respecto del índice principal. Alias, manifiestos, modelo, captura, CSV y configuración recuperados. |
| Sin proveedor externo | API sin ruta externa, OpenAlex inaccesible, modelo cargado localmente y búsqueda operativa. Reinicio del stack conservó disponibilidad y 100 IDs únicos. |
| Navegador | Consulta ES, ficha y procedencia, referencia confirmada en portapapeles, filtro sin resultados y error por fechas invertidas. |
| API funcional | Paginación sin duplicados, ficha sin resumen, vacío, fechas inválidas y generación inexistente mediante el script HTTP sobre la demo restaurada. |

## Archivos

- `backend/app/recovery.py`: respaldo y restauración; CLI `backup`/`restore`.
- `compose.recovery.yaml`: instancia separada; API sin salida externa.
- `scripts/check_recovery.py`: comparación exacta, piloto real y rollback; verifica que el principal quede intacto.
- `scripts/check_offline.py`: prueba de bloqueo externo y readiness desde el contenedor.
- `evidence/scrum-14-recovery.json`: resultados del piloto y comparación exacta.
- `evidence/scrum-14-offline.json`, `evidence/scrum-14-restart.json`: disponibilidad sin OpenAlex antes y después de reiniciar.
- `evidence/scrum-14-search.json`: comprobaciones HTTP del corpus restaurado. Los tiempos incidentales del script no son una evaluación de relevancia ni una comparación de modelos.
- `evidence/scrum-14-browser.png`: recorrido de la demo principal.

El respaldo local se conserva en `data/recovery/backup` (29 archivos con hash); la restauración en `data/recovery/restored`. Están excluidos de Git. No contienen la clave OpenAlex. La demo principal conserva `s13_20261105_v2`, con 100 publicaciones, 90 resúmenes y 10 registros solo con metadatos.

## Límites

La evaluación de calidad y RAGAS sigue en Sprint 3. El buscador actual devuelve publicaciones y referencias; el chat con respuesta fundamentada está previsto para Sprint 2. Este cierre no completa el retiro de generaciones de SCRUM-26 ni la revisión global de documentación de SCRUM-15. El respaldo recupera la generación activa, no todas las generaciones históricas ni el entorno Docker completo.
