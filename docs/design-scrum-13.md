# Dirección de interfaz de SCRUM-13

Una mesa de consulta bibliográfica para estudiar detección de caídas en el hogar. La acción principal es escribir una pregunta temática y leer publicaciones; los datos de cobertura acompañan el trabajo sin ocupar el lugar de los resultados.

Paleta: fondo azul papel `#EDF2F7`, superficie blanca `#FFFFFF`, tinta `#132B4F`, acción azul `#235FD6`, texto secundario `#56667A`, separación `#CCD7E5`. Tipografía local Aptos/Segoe UI: títulos de documentos 21 px, texto 16 px, metadatos 14 px; alineación izquierda y resúmenes de menos de 80 caracteres por línea.

```text
Observatorio                         Estado de la colección
Literatura sobre detección de caídas
[ Consulta en español o inglés                     ][Buscar]
Ejemplos de consultas                 Cobertura y actualización

[Fechas y tipo]   Documentos que cumplen los filtros
[Aplicar]        Título de la publicación
[Limpiar]        Autores, fecha, tipo, contenido disponible
                 Extracto y acceso a lectura
                 ...
                 [Anterior] Página actual [Siguiente]

Detalle: ventana de lectura con resumen, fuente y referencia.
```

En móvil los filtros se pliegan encima de la lista y el detalle ocupa la pantalla. No se muestran puntuaciones como probabilidades ni controles de funciones futuras. Los cambios de consulta/filtros reinician la página y la versión de colección; paginación y detalle conservan la versión usada al buscar.

Revisión del diseño antes de construir: se sustituye la portada de preparación en crema/serif y sus números decorativos por una herramienta de lectura. El elemento distintivo será el campo de consulta con una marca lateral azul, acompañado de una lista bibliográfica continua. Se evita convertir cada metadato en una tarjeta. Foco visible, navegación por teclado, mensajes concretos y movimiento reducido forman parte del recorrido.

Revisión posterior: se verificaron consulta, paginación, lectura sin resumen y copia real al portapapeles. En móvil (390 × 844), los filtros empiezan plegados y el detalle ocupa toda la pantalla. La revisión visual detectó que el relleno de campos ampliaba el ancho del panel: se fijó `border-box` para que fecha y tipo permanezcan dentro de sus columnas; ancho de contenido y de layout coinciden en 375 px, descontada la barra vertical. La confirmación de copia se trasladó arriba para dejar disponibles los botones del detalle. [Captura móvil](../docs/evidence/scrum-13-mobile.png).
