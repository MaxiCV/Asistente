# Revisión de literatura

Vocabulario del corpus de publicaciones y sus versiones disponibles para consulta.

## Language

**Generación**:
Versión concreta del corpus, sus fragmentos y la configuración con la que se prepararon para buscar.
_Avoid_: Lote de captura, snapshot

**Generación candidata**:
Generación preparada para validación que todavía no tiene una publicación confirmada.
_Avoid_: Generación histórica

**Generación activa**:
Generación publicada que se elige para iniciar las consultas nuevas.
_Avoid_: Última generación construida

**Generación histórica**:
Generación publicada anteriormente que permite continuar consultas de esa misma versión mientras se conserve disponible.
_Avoid_: Copia de respaldo, candidata

**Manifiesto de generación**:
Descripción de la procedencia, configuración, contenido y conteos de una generación.
_Avoid_: Recibo de publicación

**Recibo de publicación**:
Evidencia de la primera publicación confirmada de una generación, vinculada a su manifiesto.
_Avoid_: Generación activa, registro de intento

**Generación fijada**:
Generación elegida al comenzar una consulta y conservada durante esa consulta aunque cambie la activa.
_Avoid_: Generación actual

**Conversación**:
Hilo persistente de preguntas y respuestas, ligado a la generación elegida en su primer turno.
_Avoid_: Sesión de búsqueda, generación

**Turno**:
Pregunta y respuesta guardadas juntas, con orden, configuración, contexto y citas. Su ID de envío permite recuperar el mismo resultado al reintentar.
_Avoid_: Intento remoto, mensaje sin confirmar

**Contexto recuperado**:
Fragmentos de la colección seleccionados para la pregunta actual. Recuperarlos no significa que sean relevantes ni que se citen todos.
_Avoid_: Evidencia evaluada, historial

**Cita**:
Referencia numerada a un documento y fragmento del contexto del turno. Permite abrir la ficha de esa generación; la comprobación de IDs no demuestra fidelidad semántica.
_Avoid_: Garantía de exactitud

**Evidencia insuficiente**:
Estado que indica que el contexto no permite responder o que la estructura de citas fue rechazada. No demuestra ausencia de antecedentes en toda la literatura.
_Avoid_: Error de conexión, cero resultados globales
