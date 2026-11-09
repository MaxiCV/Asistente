# Product

<!-- impeccable:product-schema 1 -->

Contexto del producto confirmado el 8 de noviembre de 2026. Este documento describe el MVP completo y distingue sus capacidades actuales de las previstas. Los registros de implementación y el backlog mantienen el estado detallado de cada entrega.

## Platform

web

## Users

Estudiantes e investigadores que exploran antecedentes científicos y tecnológicos para actividades de investigación y desarrollo (I+D). Necesitan formular una consulta, encontrar documentos pertinentes, revisar su contenido disponible y conservar referencias que puedan verificar.

El dominio inicial es la detección de caídas en el hogar mediante Machine Learning y Deep Learning, con personas mayores como escenario principal de los estudios. Las personas mayores son parte del dominio investigado; no se ha definido que sean el público de la aplicación.

## Product Purpose

Reunir la búsqueda de publicaciones científicas y patentes con la consulta conversacional de los documentos recuperados, para apoyar la exploración de antecedentes de I+D mediante una plataforma web modular.

El recorrido objetivo permite buscar, filtrar, revisar fuentes, copiar referencias y formular preguntas de seguimiento. Las respuestas asistidas por IA deben vincularse a evidencia documental e indicar cuándo el material recuperado no permite responder.

El éxito del MVP exige una demostración reproducible, funciones verificadas y una evaluación documentada de pertinencia y respaldo de las respuestas. La evaluación de calidad está prevista para el Sprint 3: su meta de al menos 8 de 10 consultas con un documento relevante entre los primeros cinco resultados es un criterio por comprobar, no un resultado obtenido.

## Positioning

El mecanismo del producto combina un corpus temático seleccionado y revisado, recuperación local y trazabilidad hasta los registros originales. La búsqueda y la futura conversación deben conservar identificadores, procedencia y referencias verificables.

Se trabaja sobre la colección disponible y su contenido real. El producto no presupone cobertura exhaustiva, texto completo ni acceso en tiempo real a todas las fuentes científicas y de patentes.

## Operating Context

- MVP académico con desarrollo y revisión por incrementos, dentro de un horizonte aproximado de diez semanas. El responsable del proyecto prioriza, desarrolla y acepta el trabajo; el profesor puede participar en las revisiones.
- Demostración local reproducible desde el navegador, con interfaz adaptable a escritorio y móvil. La web móvil sigue siendo una plataforma web.
- Interfaz en español; consultas en español e inglés sobre documentos en esos idiomas.
- Flujo disponible: escribir una consulta, aplicar filtros de fecha y tipo, recorrer resultados, abrir una ficha, revisar título/resumen/procedencia, visitar la fuente y copiar la referencia.
- La CLI captura, prepara, publica y mantiene el corpus; la interfaz web consulta la API. La API no recibe la clave de OpenAlex.
- La búsqueda semántica actual funciona sin consultar proveedores externos cuando el corpus y los pesos del modelo ya están preparados. La captura, la descarga inicial de pesos y la apertura de fuentes externas sí requieren conectividad.
- La paginación y el detalle mantienen la versión de colección elegida al comenzar la búsqueda. Una actualización del corpus no debe cambiar silenciosamente los documentos de esa consulta.

Las instrucciones de ejecución y mantenimiento están en [README.md](README.md) y [docs/demo-local.md](docs/demo-local.md). El vocabulario de generaciones, manifiestos y publicación se mantiene en [GLOSSARY.md](GLOSSARY.md).

## Capabilities and Constraints

### Capacidades disponibles y previstas

Estado de referencia al 8 de noviembre de 2026, según el código y los registros del repositorio; no constituye una nueva ejecución de sus pruebas.

| Área | Disponible | Previsto para el MVP |
| --- | --- | --- |
| Fuentes | Publicaciones capturadas de OpenAlex, con metadatos y resúmenes cuando existen. | Al menos una fuente de patentes. EPO OPS es un candidato sujeto a acceso y condiciones de uso. |
| Búsqueda | Recuperación semántica local, consultas ES/EN, filtros por fecha y tipo, resultados sin documentos duplicados y paginación. | BM25 y búsqueda híbrida mediante fusión RRF en Qdrant, desde Sprint 2. |
| Lectura y referencias | Ficha con contenido disponible, procedencia, enlaces, clasificación preliminar y copia de referencia. Los registros sin resumen se identifican como solo metadatos. | Preservar estas garantías al incorporar patentes y conversación. |
| Conversación | No implementada en el incremento actual. | Chat con RAG y referencias desde Sprint 2; completar seguimientos y evaluar respuestas en Sprint 3. |
| Corpus y recuperación | Snapshots, revisión CSV, construcción por generaciones, publicación, rollback y respaldo/restauración de la generación activa. | Retiro controlado de generaciones, todavía pendiente según el registro del proyecto. |
| Validación | Registros de pruebas funcionales, integración, recuperación, operación offline y recorridos de navegador. | Evaluación de relevancia y respaldo de respuestas, comparación de modos de búsqueda y arnés RAGAS en Sprint 3. |

### Restricciones que deben preservarse

- La integración mínima del MVP comprende una fuente científica y una de patentes. Crossref, The Lens y Semantic Scholar son posibilidades futuras, no integraciones disponibles ni compromisos adicionales.
- El corpus inicial de publicaciones contempla registros desde 2020, un piloto de 20 documentos únicos y una meta de 100, con al menos 80 % de resúmenes utilizables. Las decisiones de inclusión/exclusión, tecnología y evidencia se registran en CSV versionados.
- No inventar resúmenes, autores, fechas, clasificaciones ni evidencia ausente. La clasificación basada en título y resumen es preliminar. Los títulos sin resumen no equivalen a documentos leídos íntegramente.
- Las futuras síntesis utilizarán contenido recuperado, citarán documentos de ese contexto e indicarán si solo se dispone de resúmenes o si la evidencia es insuficiente.
- La similitud semántica no es una probabilidad ni garantiza pertinencia. Un resultado vacío no demuestra que no existan antecedentes.
- El procesamiento inicial es textual. No incluye interpretación especializada de imágenes, diagramas ni estructuras químicas, ni conclusiones jurídicas de patentabilidad, infracción o libertad de operación.
- La cobertura depende de las fuentes, sus licencias, cuotas y calidad. No se garantiza acceso a texto completo, exhaustividad ni actualización en tiempo real.
- Se integran modelos preentrenados; no se entrenará un modelo fundacional ni se desarrollarán nuevos algoritmos de IA. Se prioriza la relevancia con velocidad local, favoreciendo menor latencia cuando la calidad sea comparable.
- Se priorizan servicios gratuitos o compatibles con el presupuesto de demostración. Las respuestas de IA requerirán revisión de sus fuentes; no se ha acreditado calidad para otros dominios.
- El MVP no incluye alta disponibilidad, administración avanzada de usuarios ni operación empresarial a gran escala. La entrega académica no supone certificación para producción.
- La arquitectura vigente usa React/TypeScript para la web, Python/FastAPI para API y CLI, y Qdrant como única base de datos, junto con archivos persistentes. No se reincorpora una etapa relacional. API y CLI son procesos distintos con un núcleo Python compartido.
- Las dependencias vigentes están fijadas en los manifiestos y lockfiles. El modelo local actual es multilingual-e5-small con revisión fijada; otros modelos siguen siendo candidatos. LlamaIndex está previsto desde Sprint 2 y RAGAS desde Sprint 3.
- Las credenciales permanecen fuera del código, los snapshots y la interfaz. Las nuevas generaciones se verifican antes de publicarse y se conserva la posibilidad de recuperación.

### Decisiones abiertas

- Selección y autorización definitivas de la fuente de patentes; EPO OPS aún es candidato.
- Proveedor/modelo generativo y sus condiciones operativas para el chat.
- Nombre definitivo del producto y compromisos de marca. La interfaz actual utiliza «Observatorio» y el repositorio «Asistente de revisión de literatura»; estos nombres existentes no constituyen una decisión de marca nueva.
- Requisitos de despliegue posteriores a la demostración local y cualquier ampliación del dominio o del público.
- Estándar formal de accesibilidad y validación específica con usuarios; no se declara una certificación.

## Evidence on Hand

- [Propuesta académica vigente](../propuesta_asistente_id/main.tex): objetivos, usuarios, dominio, alcance del MVP, restricciones y planificación. Este archivo pertenece a la carpeta de propuesta que acompaña al repositorio.
- [README.md](README.md): capacidades actuales, arranque, CLI y mantenimiento.
- [docs/architecture/README.md](docs/architecture/README.md) y [docs/contracts/README.md](docs/contracts/README.md): decisiones arquitectónicas y contratos de datos.
- [corpus/README.md](corpus/README.md), [corpus/revision_corpus.csv](corpus/revision_corpus.csv) y [corpus/revision_piloto.csv](corpus/revision_piloto.csv): selección revisada y referencias a registros reales de OpenAlex.
- [docs/implementation-scrum-13.md](docs/implementation-scrum-13.md) y [docs/implementation-scrum-14.md](docs/implementation-scrum-14.md): implementación y comprobaciones registradas. La colección documentada contiene 100 documentos, 90 con resumen y 103 fragmentos; el piloto contiene 20 documentos, 18 con resumen. Son conteos de una generación concreta, no constantes del producto.
- [Captura de escritorio](docs/evidence/scrum-13-desktop.png), [captura móvil](docs/evidence/scrum-13-mobile.png) y [recorrido de navegador](docs/evidence/scrum-14-browser.png): evidencia visual existente.
- [docs/design-scrum-13.md](docs/design-scrum-13.md): referencia del diseño ya implementado, mantenida separadamente de este contexto de producto.

Los snapshots, pesos y respaldos locales se conservan fuera de Git en `data/`; clonar el código no basta para recuperar esos artefactos. Los registros operativos y funcionales disponibles no acreditan por sí solos relevancia de resultados ni calidad de respuestas. No hay testimonios, clientes, certificaciones ni resultados comparativos de calidad confirmados para usar como prueba comercial.

## Product Principles

1. **Conservar la trazabilidad.** Cada documento y futura respuesta debe permitir revisar la fuente y el contenido que la sustenta.
2. **Explicitar los límites de la evidencia.** Distinguir metadatos, resúmenes y contenido disponible; reconocer ausencias e incertidumbre sin completar datos inventados.
3. **Proteger la continuidad de la consulta.** Mantener referencias y versión de colección coherentes durante búsqueda, paginación y lectura.
4. **Priorizar el recorrido completo del MVP.** Buscar, revisar y consultar evidencia antes de ampliar fuentes o funciones secundarias; verificar cada incremento en la demostración reproducible.
5. **Separar implementación y evaluación.** Mostrar como disponible lo comprobado, mantener explícito lo previsto y respaldar las afirmaciones de calidad con evaluación documentada.

## Accessibility & Inclusion

Preservar los requisitos ya documentados de navegación por teclado, foco visible, mensajes concretos y respeto por movimiento reducido. Los controles deben tener etiquetas comprensibles y los estados de carga, error y resultado vacío deben poder entenderse y recuperarse.

El acceso desde móvil debe conservar búsqueda, filtros, lectura y referencias. Si el navegador no permite copiar, la referencia debe seguir disponible como texto seleccionable. La interfaz utiliza español y admite consultas ES/EN; no se presupone que el usuario conozca los detalles de embeddings, índices o generaciones para completar su tarea.
