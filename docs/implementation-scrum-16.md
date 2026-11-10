# SCRUM-16 · Conector de patentes, primer incremento

Implementación iniciada el 10 de noviembre de 2026 en `feat/scrum-16-epo-ops`.
No se declara terminado el ticket: falta una captura autenticada real, revisión de
su contenido y condiciones de uso, y revisión/integración del código.

## Fuente evaluada

EPO OPS es el candidato inicial: ofrece bibliografía de patentes mediante API XML
y requiere registro y autenticación de aplicación. Referencias oficiales consultadas:

- [Portal de desarrolladores EPO](https://developers.epo.org/home-page).
- [Registro y control de uso](https://www.epo.org/en/service-support/faq/searching-patents/open-patent-services/ops-v32/why-registration-needed-ops-32).
- [Restricciones de acceso](https://www.epo.org/en/service-support/faq/searching-patents/open-patent-services/general-information/are-there-any).
- [Guía OPS 3.2, versión 1.3.20](https://link.epo.org/web/searching-for-patents/data/en-ops-v3.2-documentation-version-1.3.20.pdf).

Se usa HTTPS, OAuth de aplicación y `published-data/search/biblio`. Se capturan
metadatos y el resumen cuando viene en la respuesta bibliográfica; no se descargan
reivindicaciones, descripciones completas, imágenes ni PDFs. Antes de distribuir
un corpus real, comprobar los términos aplicables a la cuenta y al contenido obtenido.

## Uso

Registrar una aplicación OPS en el portal y configurar en `.env`:

```dotenv
EPO_OPS_CONSUMER_KEY=
EPO_OPS_CONSUMER_SECRET=
```

No usar la contraseña personal del portal. Ambas variables son `SecretStr` y se
leen solo para la CLI; no se incorporaron a Compose ni al frontend.

```powershell
.\.venv\Scripts\python.exe -m app.cli fetch-patents mi_captura_ops
# Otra consulta CQL y límites: crear un archivo basado en config/epo_ops.json.
.\.venv\Scripts\python.exe -m app.cli fetch-patents otra_captura --config config/epo_ops.json
```

La configuración inicial consulta `ta="fall detection"`, con hasta 25 registros.
El resultado queda en `data/patents/snapshots/<id>/`: páginas XML, `patents.jsonl`
y manifiesto con configuración, fechas de captura, hashes SHA-256, conteos y
estado. El identificador debe ser nuevo; no se sobrescriben capturas anteriores.
`complete` significa lote configurado terminado, no descarga de todos los resultados.
No ejecutar capturas concurrentes con la misma cuenta: el control de frecuencia
de esta versión es local al proceso.

## Normalización y errores

`PatentDocument` preserva identidad DOCDB `país.número.kind`, fecha de publicación,
título, idioma, resumen disponible, fuente, URL OPS, snapshot y momento de captura.
Conserva el código de publicación (por ejemplo A1 frente a B1); no agrupa familias.
Elige inglés, español o el primer idioma disponible sin traducir. Fechas ausentes
y títulos ausentes quedan nulos; identidades y fechas inválidas rechazan la página.
El idioma del resumen se conserva separado del idioma del título.

El cliente reutiliza el token hasta su vencimiento y permite una renovación ante
401. Los reintentos de transporte, 408, 429 y ciertos 5xx están acotados, respetan
`Retry-After` y cuentan contra un presupuesto total que incluye autenticación.
El intervalo mínimo es seis segundos; el límite dinámico de `X-Throttling-Control`
puede aumentarlo. Un estado negro o HTTP 403 detiene la captura. No se reintentan
errores permanentes, ni se siguen redirecciones. El bloqueo de cuota puede exigir
esperar o revisar la cuenta antes de lanzar una nueva captura.

No se persisten tokens, credenciales ni cuerpos de errores HTTP. Los errores
dejan el manifiesto incompleto; una interrupción abrupta conserva el estado inicial
incompleto. XML malformado, DTD/entidades y páginas truncadas se rechazan.

## Validación y trabajo restante

Las pruebas HTTP usan `httpx.MockTransport` y XML sintético identificado como tal.
Cubren paginación, deduplicación, normalización, hashes, secretos, cuota dinámica,
reintentos, renovación de token, errores y conservación de capturas incompletas.

Resultado local: 23 pruebas nuevas aprobadas; suite completa con 118 aprobadas
y 14 omitidas de integración sin `QDRANT_TEST_URL`. `ruff check backend`,
`ruff format --check backend` y `git diff --check` aprobados. Se exportaron los
esquemas de `PatentDocument` y `PatentFetchConfig`. Para evitar permisos denegados
en el directorio temporal compartido de Windows, pytest se ejecutó con
`-p no:cacheprovider --basetemp <directorio_nuevo_en_.cache>`.

No hay credenciales EPO OPS configuradas en el entorno revisado. Queda pendiente
confirmar con respuestas reales las variantes de errores (incluidos 400 por token
y 404 de búsquedas sin resultados). Por ahora 400 y 404 fallan de forma explícita;
no se convierten en capturas vacías exitosas.

El índice y la API existentes aceptan exclusivamente `Document` de publicaciones.
Este incremento mantiene un contrato separado de captura de patentes; la revisión
del corpus, la adaptación de indexación, filtros, búsqueda y UI quedan pendientes
para la búsqueda integrada. No cambia los alias ni la generación publicada.
