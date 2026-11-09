# Demo local y recuperación — SCRUM-14

Verificada el 7 de noviembre de 2026. Ejecutar desde `Asistente` en PowerShell.

## Preparar y mostrar

```powershell
docker compose up -d --build
.\.venv\Scripts\python.exe -m app.cli check-env
Invoke-RestMethod http://localhost:8000/api/v1/ready
```

Esperar `status: ready` antes del recorrido. La salud del proceso no sustituye este chequeo: también deben estar disponibles Qdrant, el modelo y el corpus. Abrir <http://localhost:5173/>.

1. Comprobar cobertura: **100 publicaciones, 90 con resumen y 10 solo con metadatos**.
2. Pulsar «Detección de caídas con cámaras»; revisar orden y paginación. Cada publicación aparece una vez.
3. Abrir una ficha, revisar resumen, procedencia y DOI; copiar la referencia.
4. Buscar «Wearable fall detection at home»; probar tipo y fechas.
5. Usar fecha inicial `2099-01-01`: mostrar el estado vacío. Agregar fecha final `2020-01-01`: mostrar el error de intervalo. Limpiar filtros.
6. Explicar que los documentos sin resumen se recuperan solo por título. No se usa texto completo ni se genera todavía una respuesta.

Las consultas demuestran funcionamiento, no relevancia validada. RAGAS, juicios de relevancia y comparación de recuperadores quedan en Sprint 3. BM25/híbrida y chat siguen en Sprint 2.

## Crear respaldo comprobado

```powershell
.\.venv\Scripts\python.exe -m app.cli backup --output data/recovery/backup
```

El destino debe ser nuevo. El comando toma el bloqueo del escritor y respalda **solo la generación activa**: snapshots nativos de ambas colecciones, alias, manifiesto y recibo de publicación, captura OpenAlex original, CSV usado, configuración, dependencias fijadas, registros y pesos locales. Verifica procedencia, integridad y contenido del índice antes de respaldar. Publica `backup.json` al final; sin ese archivo el respaldo no está completo. No copia `.env`, credenciales ni cachés.

Los alias se guardan aparte porque los snapshots de colección no los incluyen. Véase la [documentación de snapshots de Qdrant](https://qdrant.tech/documentation/snapshots/).

El paquete sirve para recuperar datos y configuración con esta versión del código. **No incluye el código fuente ni las imágenes Docker**: conservar también el repositorio y las imágenes ya construidas para una instalación sin Internet. No reemplaza un respaldo de todas las generaciones históricas. Copiar el paquete completo a otro disco permite sobrevivir a la pérdida del disco de trabajo.

## Ensayo de restauración aislada

Los directorios `data/recovery/backup` y `data/recovery/restored` ya contienen el ensayo ejecutado. Los siguientes comandos describen una instalación nueva; no sobrescriben esos resultados. Para repetir desde cero usar destinos nuevos, un proyecto Compose distinto y ajustar los dos mounts de `compose.recovery.yaml`. No reutilizar un volumen con datos.

```powershell
docker compose -f compose.recovery.yaml up -d qdrant
$env:QDRANT_URL = 'http://127.0.0.1:6335'
.\.venv\Scripts\python.exe -m app.cli restore --backup data/recovery/backup --output data/recovery/restored
Remove-Item Env:QDRANT_URL
docker compose -f compose.recovery.yaml up -d api web
```

Abrir <http://localhost:5174/>. La API restaurada usa una red interna sin ruta a Internet; el frontend ofrece acceso local y Qdrant permite administración en `127.0.0.1:6335`. La API no recibe la clave OpenAlex.

`restore` verifica hashes, modelo, manifiestos y CSV antes de escribir. Exige Qdrant **1.20.0**, vacío y exclusivo, además de un directorio nuevo. Restaura primero los datos y valida ambas colecciones; solo después publica los dos alias juntos. No se debe ejecutar otro escritor en el destino durante la restauración.

Si falla una carga, conservar el destino para diagnóstico: no hay rollback automático ni se publican alias antes de validar las dos colecciones. Corregir la causa y usar un destino nuevo y vacío. Un respaldo alterado se rechaza antes de modificar Qdrant.

```powershell
# Verifica dentro del contenedor que OpenAlex y el acceso TCP externo están bloqueados.
Get-Content -Raw scripts/check_offline.py | docker compose -f compose.recovery.yaml exec -T api python -
# Compara todos los payloads/vectores, construye el piloto real, lo publica y vuelve a 100 documentos.
.\.venv\Scripts\python.exe scripts/check_recovery.py
# Comprueba persistencia; esperar ready otra vez al reiniciar el modelo.
docker compose -f compose.recovery.yaml restart
Get-Content -Raw scripts/check_offline.py | docker compose -f compose.recovery.yaml exec -T api python -
```

`check_recovery.py` usa exclusivamente el Qdrant de recuperación para escribir y crea una generación piloto nueva en cada ejecución. Lee el corpus principal para comparar y comprueba que no cambió. El piloto usa `corpus/revision_piloto.csv` del repositorio. Después del ensayo:

```powershell
docker compose -f compose.recovery.yaml stop
```

La demo principal sigue en el puerto 5173. No usar `down -v`: elimina los volúmenes.

## Fallos y vuelta a la generación anterior

- Captura interrumpida con Ctrl+C: snapshot incompleto, registros parciales conservados, no elegible para indexar; repetir con ID nuevo.
- Build interrumpido con Ctrl+C: ejecución fallida, candidata retenida, bloqueo liberado y corpus activo disponible; repetir con generación nueva.
- Terminación forzada o corte de energía: puede quedar el bloqueo `data/index-writer.lock` y un registro `running`. Detener/verificar que no exista otro escritor antes de retirar manualmente ese bloqueo. No publicar una candidata sin manifiesto validado. Las pruebas automatizadas de interrupción cubren Ctrl+C simulado, no un corte físico de energía.
- Timeout al publicar: si ambos alias ya apuntan a la candidata, se reconcilia como éxito; si no se confirma, se informa fallo y se inspecciona el estado antes de reintentar.
- Rollback: `python -m app.cli rollback <generacion_publicada>` valida la generación y cambia ambos alias en una operación. No modifica los documentos históricos.
- Modelo ausente, corpus inconsistente o dependencia caída: respuesta 503; no se representa como una lista vacía. Una versión retirada solicitada por un lector devuelve 409 y permite reiniciar la búsqueda.

El retiro administrativo de generaciones continúa pendiente en SCRUM-26. No forma parte de este ensayo ni es necesario para recuperar la demo.
