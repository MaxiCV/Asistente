# Implementación de SCRUM-10 y SCRUM-11

Registro del 4 de noviembre de 2026 (America/Santiago). Implementación local en el repositorio Asistente.

## Resultado

**SCRUM-10 completado:** web React/TypeScript/Vite, API FastAPI, CLI Python y Qdrant 1.20.0 arrancan localmente. Versiones y dependencias bloqueadas. Clave OpenAlex verificada sin exponerla; modelo E5 descargado por revisión y comprobado offline.

**SCRUM-11 completado:** contratos ejecutables de documentos, fragmentos, identidades, snapshots, CSV, manifiestos y API. Modelo C4 validado, propiedad de escrituras documentada, creación repetible de colecciones e índices y resolución coherente de alias implementadas.

## Evidencia

| Comprobación | Resultado |
| --- | --- |
| Tests de contratos, CSV, API, OpenAlex simulado y fijación de generación | 34 aprobados; prueba de integración separada |
| Integración Qdrant real | 1 aprobada: payload sin vectores, vector dense de 384 dimensiones, índices, lectura desde otro cliente y protección al existir alias |
| Ruff | Sin errores; 23 archivos formateados |
| Frontend | TypeScript y build Vite correctos, también durante construcción Docker |
| Docker Compose | API, web y Qdrant levantados; API healthy |
| Web | HTTP 200 y revisión visual en navegador; muestra colección en preparación |
| API health | HTTP 200, status ok |
| API ready | HTTP 503 esperado: qdrant=true, model=true, corpus=false |
| Persistencia | Pareja vacía documents_bootstrap_20261105/passages_bootstrap_20261105 conservada tras reiniciar Qdrant; sin alias publicados |
| OpenAlex | Clave aceptada, cursor confirmado y endpoint de cuota verificado; respuesta de salida limita campos y omite secretos |
| Modelo offline | Revisión 614241f622f53c4eeff9890bdc4f31cfecc418b3, 9 archivos con SHA-256; dos entradas ES/EN producen vectores finitos y normalizados de 384 dimensiones |
| C4 | Structurizr validate termina con código 0 |
| Contratos exportados | 17 JSON Schema y OpenAPI |
| Credenciales | Clave ausente de archivos versionables; .env, .venv, data y cachés ignorados por Git |

Comandos reproducibles en el [README](../README.md). Las pruebas de integración eliminan únicamente sus colecciones/alias con UUID. La pareja bootstrap vacía se conserva como evidencia de persistencia y no es una colección de publicaciones.

## Límites de este incremento

- No se ha capturado el piloto ni publicado un corpus. El CSV real contiene únicamente encabezados.
- Búsqueda, detalle y cobertura tienen contrato y validación, pero responden 503 explícito hasta implementar SCRUM-12/26/13.
- Publicación, rollback y navegación histórica están especificados; su implementación corresponde a SCRUM-26 y SCRUM-13.
- La prueba inicial offline en Windows registró 112,786 s de carga y 1,786 s para un lote de dos textos. Incluye el arranque inicial de dependencias; no es un benchmark estable, una latencia por consulta ni una evaluación de relevancia. Registrar mediciones repetidas de rendimiento en SCRUM-26 y al integrar la búsqueda.
- No se ha medido calidad de recuperación; RAGAS, consultas anotadas y comparación de modelos permanecen en Sprint 3.
- No hay base relacional. LlamaIndex y BM25/híbrida permanecen en Sprint 2.

La siguiente tarea del flujo es **SCRUM-12: captura OpenAlex y revisión del piloto**, en paralelo lógico con la preparación de embeddings/indexación de SCRUM-26, pero ejecutables secuencialmente por un desarrollador.

