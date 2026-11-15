# Correcciones de SCRUM-16/17 — 14 de noviembre de 2026

Revisión e implementación por Codex, sin dependencia de Claude. Se atienden A-01, A-02 y A-03 de la auditoría del 13 de noviembre y dos puntos de A-08.

- La interfaz consulta `manifest.bm25`, conserva los códigos de error y recupera `search_mode_unavailable` con búsqueda semántica y criterios editados.
- El tipo documental se puede identificar y limpiar; `all` no cuenta como filtro. El vacío léxico distingue falta de términos de ausencia de documentos filtrados.
- Manifiesto y catálogo exigen procedencia para patentes. Respaldo/restauración contrastan los documentos de patente con la selección inmutable; los nuevos respaldos incluyen `config/epo_ops.json`. No se incluyen credenciales.
- CI comprueba contratos exportados y ejecuta restauraciones en un segundo Qdrant vacío. Se añade cobertura HTTP del modo incompatible.

Verificación: 135 pruebas unitarias, 21 de integración con Qdrant 1.20.0, Ruff y build TypeScript/Vite. Se comprobó el ciclo `backup → verify → restore → búsqueda lexical/hybrid` con vectores sintéticos, patentes y BM25 real, sin modificar alias publicados del corpus del usuario. También se comprueba rechazo de XML/selección alterados y manifiestos con hashes recalculados pero sin procedencia. No es una evaluación de relevancia.

La copia inmutable `data/generations/<g>/patent_selection.json` es la selección respaldada; el archivo de trabajo `corpus/patent_selection.json` puede diferir y no reemplaza la procedencia publicada. Respaldos anteriores válidos siguen aceptándose sin `config/epo_ops.json`.

A-06/A-07 se atienden con SCRUM-18. A-04, A-05, el resto de A-08 y A-09 permanecen documentados para trabajo posterior.
