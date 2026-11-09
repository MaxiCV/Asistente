# Actualización del frontend — 9 de noviembre de 2026

La interfaz de búsqueda y lectura conserva la identidad azul del proyecto y da prioridad a la consulta, los filtros y las publicaciones. La aplicación actualizada está disponible localmente en `http://localhost:5173/`.

## Cambios

- Cabecera e introducción más compactas, búsqueda destacada y resultados con rango y total de publicaciones.
- Distinción entre criterios aplicados y cambios pendientes. Los filtros aplicados pueden quitarse individualmente o limpiarse sin enviar una consulta que todavía está en edición.
- Validación accesible del intervalo de fechas y recuperación desde búsquedas sin resultados.
- Ficha de lectura con título legible, procedencia, estado explícito cuando falta el resumen y acciones de cierre y copia de referencia accesibles en móvil.
- Enlace para saltar a la búsqueda, foco en resultados tras consultar o paginar, controles principales de al menos 44 px y respeto de la preferencia de movimiento reducido.
- Nombre accesible de la ficha independiente del botón de cierre.

El alcance sigue siendo el buscador del corpus local de publicaciones. Las funciones previstas del MVP permanecen documentadas en `PRODUCT.md`.

## Validación realizada

Comprobaciones manuales del 8 y 9 de noviembre con la API y el corpus reales de 100 publicaciones:

| Recorrido | Resultado |
| --- | --- |
| Consulta de ejemplo y paginación | Rangos 1–10 y 11–20, con retorno a la primera página y foco en resultados. |
| Filtros por tipo y fecha | Aplicación, eliminación individual y limpieza correctas. |
| Consulta pendiente al limpiar filtros | Se conserva el texto en edición y se vuelve a buscar con la consulta aplicada. |
| Fechas invertidas | Mensaje asociado a los campos y envío deshabilitado. |
| Búsqueda sin coincidencias | Estado vacío y recuperación mediante «Buscar sin filtros». |
| Publicación sin resumen | Estado explícito; referencia copiada y contrastada con el texto mostrado. |
| Teclado | Envío de búsqueda y navegación de foco comprobados. |
| Adaptación de pantalla | Sin desbordamiento horizontal a 320, 390, 768 y 1280 px; ficha a pantalla completa en móvil. |
| Nombre accesible del diálogo | «Ficha de la publicación», sin incluir la acción «Cerrar ficha». |

La compilación TypeScript/Vite y la reconstrucción del servicio web de Docker finalizaron correctamente. El detector de Impeccable no informó incidencias en los archivos revisados. Las combinaciones de texto comprobadas superan 4,5:1 de contraste (texto principal sobre fondo: 12,55:1; secundario sobre fondo: 5,21:1; secundario sobre blanco: 5,87:1; azul de acción sobre blanco: 5,71:1). Estas comprobaciones no constituyen una auditoría completa de accesibilidad ni una evaluación de relevancia de la búsqueda.

## Evidencia visual

- [Escritorio](evidence/frontend-update-desktop.png)
- [Búsqueda en móvil](evidence/frontend-update-mobile.png)
- [Ficha en móvil](evidence/frontend-update-mobile-detail.png)

## Ajustes tras los comentarios de la interfaz

Se retiraron el bloque introductorio y el indicador de conexión de la cabecera. La marca visible pasó a «Nexo», con un logo vectorial de libro abierto y puntos conectados, reutilizado como icono de pestaña. El título principal de la página es ahora la etiqueta de búsqueda «¿Qué quieres investigar?»; se conservan los avisos de error y la comprobación de disponibilidad del servicio.

La reconstrucción del servicio web y la compilación TypeScript/Vite finalizaron correctamente. Se verificaron la carga del logo, la ausencia de los dos bloques retirados, la búsqueda real con 100 publicaciones y la ausencia de desbordamiento horizontal en escritorio (1011 px) y móvil (390 px).

- [Nexo en escritorio](evidence/nexo-desktop.png)
- [Nexo en móvil](evidence/nexo-mobile.png)

## Bolder: cabecera y buscador

Se reforzó únicamente la cabecera y el bloque de consulta, conservando la paleta y la tipografía existentes. La marca utiliza un logo de 48 px y un nombre de mayor tamaño. El buscador utiliza el azul profundo existente como fondo, con el título en blanco, campo de consulta y botón más amplios, y ejemplos en azul claro. El botón dispone de estados deshabilitado y de foco visibles sobre ese fondo.

Los resultados, filtros, ficha de lectura y lógica de consulta conservan su implementación. La revisión del diff respecto al estado anterior a `bolder` confirma que los cambios se limitan a los estilos de la cabecera/buscador y las dimensiones del logo.

Validación: compilación TypeScript/Vite correcta, detector de Impeccable sin incidencias, búsqueda con Enter sobre el corpus real y foco posterior en resultados. Se revisaron vistas de 320, 390, 768 y 1011 px sin desbordamiento horizontal. El botón recibe un contorno blanco de 3 px al navegar con teclado. Contrastes comprobados: título 14,13:1, ejemplos 11,70:1 y texto del botón principal 5,71:1.

- [Bolder en escritorio](evidence/nexo-bolder-desktop.png)
- [Bolder en móvil](evidence/nexo-bolder-mobile.png)
