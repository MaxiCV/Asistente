# SCRUM-13: búsqueda local, API e interfaz

Implementado y verificado el 5 de noviembre de 2026. Colección activa: `s13_20261105_v2`, procedente del snapshot y CSV reales de SCRUM-12. **100 documentos, 90 resúmenes, 10 solo metadatos y 103 fragmentos**. La web está disponible en `http://localhost:5173`.

## Comportamiento entregado

- Consultas ES/EN mediante E5-small local, revisión fijada, 384 dimensiones, coseno y normalización. Sin descargas de modelos en la API.
- Fechas inclusivas y subtipo de publicación, agrupación por documento con score máximo de fragmento, desempate por UUID y páginas sin duplicados.
- Generación y nombres físicos fijados por petición; páginas y fichas conservan la versión. 409 ante versión retirada/no publicada; 503 ante incompatibilidad o dependencia caída; 404 para documento ausente.
- Interfaz española con estados de carga, vacío y error; filtros plegables en móvil, lista bibliográfica, detalle, procedencia y copia de referencia sencilla. Los textos originales mantienen su idioma.
- Cobertura calculada desde el manifiesto activo, separada del último intento de mantenimiento. Una actualización fallida no elimina la colección consultable.

## Base necesaria de SCRUM-26

Para poder verificar SCRUM-13 se implementaron `build`, `publish` y `rollback`. `build` reutiliza la validación de snapshots y CSV, genera nuevas colecciones, confirma las escrituras y comprueba conteos, vínculos, contenido, campos de filtro, hashes y vectores antes de finalizar el manifiesto. No hay truncado silencioso: tres documentos necesitan dos fragmentos; el máximo observado es 510 tokens, incluidos prefijo y tokens especiales.

`publish` cambia los dos alias en una sola operación. Si se pierde la respuesta, consulta los alias y reconcilia el resultado sin borrar datos. El recibo registra el hash del manifiesto y permite consultar versiones anteriores publicadas. Un escritor exclusivo evita publicaciones concurrentes.

La candidata inicial `s13_20261105` falló en validación por espacios finales en los fragmentos: no se publicó. La normalización del texto antes del hash corrigió la discrepancia; se construyó una candidata nueva, `s13_20261105_v2`. La candidata fallida queda conservada para diagnóstico. No se implementó borrado automático ni un comando de retiro de generaciones; esa parte operativa de SCRUM-26 queda pendiente y requiere mantenimiento con la API detenida. No ejecutar dos escritores; ante bloqueo residual, confirmar que el anterior terminó antes de retirar el archivo de bloqueo.

## Comprobaciones

- 67 pruebas automatizadas sin servidor aprobadas; ocho casos de integración verificados contra Qdrant 1.20.0, con colecciones y alias aislados por UUID. La ejecución sin `QDRANT_TEST_URL` omite esos ocho casos.
- Pruebas de agrupación multiframe, empate, fechas inclusivas, metadatos sin resumen, detalle, vacío, publicación entre páginas, generación retirada, modelo incompatible, fallo antes/después del commit, rollback y reproducción de IDs/contenido lógico.
- Ruff y formato Python aprobados. TypeScript y compilación de producción Vite aprobados. Servicios Docker actualizados.
- Comprobación HTTP a través del proxy web: 100 IDs únicos, dos páginas sin intersección, detalle sin resumen, filtros vacíos, 422 de fechas invertidas y 409 de versión desconocida.
- Verificación visual en navegador de consulta, ficha sin resumen, procedencia, copia real al portapapeles y paginación. Vista móvil de 390 × 844 con filtros plegables y detalle a pantalla completa. El botón de copia informa progreso y ofrece selección manual si el navegador impide el acceso; la confirmación se muestra arriba para no tapar los botones.

Los casos sintéticos prueban contratos y funcionamiento; las consultas operativas no tienen juicios de relevancia. No se ejecutó RAGAS ni evaluación de pertinencia.

## Mediciones operativas

Equipo: AMD Ryzen 5 5600X, 6 núcleos/12 hilos, aproximadamente 16 GB RAM. API Linux en Docker Desktop, CPU, cuatro hilos PyTorch; cliente HTTP en Windows. Corpus de 100 documentos/103 fragmentos. Caché de hasta 128 embeddings de consulta por proceso; no se limpió la caché de archivos del sistema operativo.

| Medición | Resultado | Condición |
| --- | --- | --- |
| Carga del codificador para `build` | 25,60 s | Proceso nuevo en Windows; incluye verificación de pesos y carga, caché de archivos sin purgar |
| Vectorización y escritura | 22,29 s | 103 fragmentos, lotes de 16; no incluye toda la construcción |
| Primera consulta HTTP | 1.868,75 ms | API recién iniciada, modelo cargado, primer uso de inferencia |
| 20 consultas distintas | p50 125,88 ms; p95 173,07 ms | Modelo caliente, embeddings de esas consultas aún sin caché |
| Las mismas 20 repetidas | p50 47,09 ms; p95 58,77 ms | Caché de embeddings caliente |
| Memoria API | 766,1 MiB | Muestra de `docker stats` después de consultar; no es pico máximo |
| Memoria Qdrant | 97,81 MiB | Misma muestra; límite de VM reportado: 15,55 GiB |

El cronómetro HTTP incluye proxy Vite, codificación de consulta, Qdrant, recuperación de metadatos, transferencia y decodificación JSON. No mide el pintado del navegador ni carga concurrente. Son muestras locales, no una garantía de latencia. No se confunde la primera consulta con el tiempo de carga del modelo.

[Muestras y comprobaciones HTTP](evidence/scrum-13-search.json), [manifiesto publicado](evidence/scrum-13-manifest.json) y [medición de construcción](evidence/scrum-13-build.json). Repetir con `python scripts/check_search.py --output data/checks/search.json`; reiniciar antes la API para que la primera pasada no reutilice embeddings anteriores.

## Límites deliberados

Se conservan E5-small y Qdrant como base única. BM25/híbrida y LlamaIndex siguen en Sprint 2. RAGAS, comparación de modelos y métricas de relevancia permanecen en Sprint 3. No se añadieron PDF, generación de respuestas ni base relacional. La lista recorre todos los documentos que cumplen filtros, ordenados por similitud; no promete que todos sean pertinentes. La estrategia de ordenación/paginación es adecuada para este corpus pequeño y rechaza colecciones filtradas de más de 10.000 documentos.
