workspace "Plataforma de búsqueda y consulta para I+D" "Sprint 1 semántica; Sprint 2 BM25/híbrida y RAG; Sprint 3 evaluación. Qdrant sin etapa relacional." {
    // Decisiones del 4 de noviembre; documentación revisada el 8 de noviembre de 2026.
    // Cinco contenedores C4 en S1; el evaluador futuro eleva el total a seis.
    !impliedRelationships false
    model {
        investigador = person "Estudiante o investigador" "Revisa literatura sobre detección de caídas en el hogar mediante ML/DL."
        responsable = person "Responsable del corpus" "Selecciona publicaciones en CSV, ejecuta la CLI y prepara modelos y respaldos."
        openalex = softwareSystem "OpenAlex" "Fuente científica principal; solo se consulta durante captura." {
            tags "Externo"
        }
        hub = softwareSystem "Hugging Face Hub" "Descarga inicial de pesos con revisión fijada; búsqueda posterior offline." {
            tags "Externo"
        }
        epo = softwareSystem "EPO OPS" "Sprint 2: patentes, sujeto a acceso y cobertura." {
            tags "Externo,Sprint2"
        }
        llm = softwareSystem "Proveedor LLM" "Sprint 2: Gemini como opción inicial para síntesis con evidencia; evaluación de respuestas en Sprint 3." {
            tags "Externo,Sprint2"
        }
        plataforma = softwareSystem "Plataforma de consulta para I+D" "Corpus local acotado; búsqueda semántica, después híbrida y conversación." {
            web = container "Aplicación web" "Busca, filtra, muestra detalle y copia referencias. Conserva index_generation al navegar." "React, TypeScript, Vite, Material UI, TanStack Query" {
                tags "Frontend"
            }
            backend = container "Backend / API" "Proceso web; módulos compartidos con CLI. LlamaIndex desde Sprint 2." "Python, FastAPI, Pydantic, qdrant-client" {
                api = component "API" "Valida entradas; expone búsqueda, detalle, corpus y disponibilidad." "FastAPI, Pydantic"
                catalogo = component "Catálogo y generaciones" "Resuelve alias una vez; fija pareja física y manifiesto; lee detalle y estado del mantenimiento." "Python, qdrant-client"
                busqueda = component "Recuperación" "S1 semántica, filtros y grupos. S2 añade BM25/RRF. Una generación por petición." "Python, qdrant-client"
                embeddings = component "Embeddings de consulta" "Pesos locales fijados; verifica compatibilidad con la generación." "Sentence Transformers, multilingual-e5-small" {
                    tags "ModeloLocal"
                }
                conversacion = component "Conversación" "Sprint 2: contexto y referencias; seguimiento completo en Sprint 3." "Python, LlamaIndex, qdrant-client" {
                    tags "Sprint2"
                }
                generacion = component "Síntesis y referencias" "Sprint 2: genera desde evidencia suficiente y comprueba IDs citados." "LlamaIndex, google-genai" {
                    tags "Sprint2"
                }
            }
            cli = container "CLI de ingesta" "Proceso de mantenimiento del mismo proyecto Python. Único escritor del corpus; fetch/build/publish." "Python, HTTPX, qdrant-client" {
                preparacion = component "Preparación de modelos" "prepare-model descarga una revisión fijada y registra hashes. check-model verifica los pesos locales." "Python, huggingface-hub"
                captura = component "Captura OpenAlex" "Escribe JSONL y manifiesto; captura incompleta no es publicable." "HTTPX, JSONL"
                construccion = component "Construcción completa" "Lee snapshot y CSV; normaliza, deduplica, fragmenta y crea pareja candidata inmutable." "Python, qdrant-client"
                embeddingsCarga = component "Embeddings de corpus" "Modelo, revisión y preparación compatibles con consulta. Control explícito de tokens." "Sentence Transformers, multilingual-e5-small" {
                    tags "ModeloLocal"
                }
                publicacion = component "Publicación y rollback" "Verifica candidata, cambia alias juntos y registra recibo. Resuelve timeout leyendo alias. Retiro controlado pendiente en SCRUM-26." "Python, qdrant-client"
            }
            datos = container "Qdrant" "Única BD. documents_g y passages_g; alias documents/passages. Historial separado desde Sprint 2." "Qdrant local persistente" {
                tags "BaseDatos"
            }
            archivos = container "Archivos persistentes" "Snapshots, CSV, manifiestos, recibos de publicación, runs y pesos fijados. Sin puntero activo independiente de alias." "Volúmenes locales, JSONL, JSON, CSV" {
                tags "Archivo"
            }
            evaluacion = container "Evaluación offline" "Sprint 3: consultas y relevancia anotada, RAGAS, comparación semántica/BM25/híbrida y revisión de respuestas." "Python, RAGAS" {
                tags "Sprint3"
            }
        }
        investigador -> plataforma "Busca y consulta referencias"
        responsable -> plataforma "Mantiene corpus, modelos y respaldos"
        plataforma -> openalex "Captura publicaciones" "HTTPS"
        plataforma -> hub "Descarga pesos fijados durante preparación" "HTTPS"
        plataforma -> epo "Desde S2 captura patentes" "HTTPS"
        plataforma -> llm "Desde S2 genera respuestas; evalúa en S3" "HTTPS"

        investigador -> web "Consulta y navega resultados" "Navegador"
        responsable -> cli "Ejecuta fetch/build/publish y mantenimiento" "CLI"
        responsable -> archivos "Revisa selección CSV y conserva respaldos" "Archivos locales"
        responsable -> evaluacion "Desde S3 ejecuta evaluación" "CLI"
        web -> backend "Búsqueda, detalle y chat desde S2" "HTTP / JSON"
        backend -> datos "Lee corpus; desde S2 conserva historial separado" "HTTP / JSON"
        backend -> archivos "Lee manifiestos, runs y pesos" "Sistema de archivos"
        backend -> llm "Desde S2 solicita síntesis" "HTTPS"
        cli -> openalex "fetch: captura publicaciones" "HTTPS / JSON"
        cli -> hub "prepare-model: descarga una revisión fijada" "HTTPS"
        cli -> epo "Desde S2 captura patentes" "HTTPS / OPS"
        cli -> datos "build/publish: escribe candidata y cambia alias" "HTTP / JSON"
        cli -> archivos "Captura, revisiones, manifiestos y pesos" "Sistema de archivos"
        evaluacion -> backend "Desde S3 consulta modos de recuperación y chat" "HTTP / JSON"
        evaluacion -> archivos "Desde S3 lee corpus congelado y guarda anotaciones e informes" "Sistema de archivos"
        evaluacion -> llm "Desde S3 evalúa respuestas cuando la métrica requiere juez" "HTTPS"

        web -> api "Envía consulta, filtros y generación" "HTTP / JSON"
        api -> catalogo "Fija generación y obtiene detalle/cobertura" "Llamada Python"
        api -> busqueda "Busca con la generación capturada" "Llamada Python"
        api -> conversacion "Desde S2 procesa preguntas" "Llamada Python"
        catalogo -> datos "Resuelve alias y lee documents_g" "HTTP / JSON"
        catalogo -> archivos "Lee manifiesto g y último intento de mantenimiento" "Archivos"
        busqueda -> embeddings "Vectoriza con la configuración fijada" "Llamada Python"
        busqueda -> datos "Consulta passages_g con filtros y agrupación; S2 añade BM25/RRF" "HTTP / JSON"
        busqueda -> catalogo "Hidrata documentos de la misma generación" "Llamada Python"
        embeddings -> archivos "Carga pesos locales fijados; offline" "Archivos"
        conversacion -> catalogo "Fija generación para todo el turno" "Llamada Python"
        conversacion -> busqueda "Recupera evidencia mediante adaptador" "Llamada Python"
        conversacion -> generacion "Entrega fragmentos suficientes e IDs permitidos" "Llamada Python"
        conversacion -> datos "Lee y guarda historial separado del corpus" "HTTP / JSON"
        generacion -> llm "Solicita síntesis con evidencia" "HTTPS"

        responsable -> preparacion "Ejecuta prepare-model o check-model" "CLI"
        preparacion -> hub "Descarga los pesos durante la preparación inicial" "HTTPS"
        preparacion -> archivos "Guarda o verifica pesos y hashes locales" "Archivos"
        responsable -> captura "Ejecuta fetch" "CLI"
        responsable -> construccion "Ejecuta build con snapshot y CSV" "CLI"
        responsable -> publicacion "Ejecuta publish o rollback" "CLI"
        captura -> openalex "Obtiene registros paginados" "HTTPS / JSON"
        captura -> archivos "Escribe JSONL y manifiesto completo o fallido" "Archivos"
        construccion -> archivos "Lee snapshot completo, CSV y configuración; escribe manifiesto g" "Archivos"
        construccion -> embeddingsCarga "Vectoriza contenido dentro del presupuesto" "Llamada Python"
        embeddingsCarga -> archivos "Carga pesos fijados offline" "Archivos"
        construccion -> datos "Crea documents_g y passages_g; confirma escrituras" "HTTP / JSON"
        publicacion -> archivos "Verifica manifiesto; registra intento y publicación confirmada" "Archivos"
        publicacion -> datos "Verifica candidata y cambia ambos alias juntos; consulta estado ante timeout" "HTTP / JSON"
    }
    views {
        systemContext plataforma "C1-Contexto" {
            include *
            autoLayout lr
        }
        container plataforma "C2-Contenedores" {
            include *
            description "Cinco contenedores C4 de S1 y un evaluador futuro en S3. Docker ejecuta tres servicios."
            autoLayout lr
        }
        component backend "C3-Backend" {
            include *
            autoLayout lr
        }
        component cli "C3-Ingesta" {
            include *
            autoLayout lr
        }
        dynamic cli "D1-Ingesta" "Sprint 1: snapshot y CSV antes de construir; publicar solo una candidata completa." {
            responsable -> captura "Ejecuta fetch"
            captura -> openalex "Captura lote configurado"
            captura -> archivos "Finaliza snapshot y manifiesto"
            responsable -> archivos "Revisa inclusión, tecnología y evidencia en CSV"
            responsable -> construccion "Ejecuta build"
            construccion -> archivos "Lee snapshot completo, CSV y configuración"
            construccion -> embeddingsCarga "Vectoriza documentos seleccionados"
            embeddingsCarga -> archivos "Usa pesos fijados locales"
            construccion -> datos "Escribe y confirma pareja candidata"
            construccion -> archivos "Finaliza manifiesto inmutable g"
            responsable -> publicacion "Ejecuta publish"
            publicacion -> archivos "Verifica manifiesto"
            publicacion -> datos "Verifica integridad y cambia ambos alias atómicamente"
            publicacion -> archivos "Registra la publicación confirmada y su recibo"
            autoLayout lr
        }
        dynamic backend "D0-BusquedaSemantica" "Sprint 1: nombres físicos fijados durante toda la petición y generación conservada al navegar." {
            investigador -> web "Consulta y filtra"
            web -> api "Envía consulta, filtros y generación opcional"
            api -> catalogo "Fija una generación completa"
            catalogo -> datos "Resuelve pareja de alias una vez"
            catalogo -> archivos "Carga manifiesto de esa generación"
            api -> busqueda "Entrega consulta y pareja física fijada"
            busqueda -> embeddings "Vectoriza con modelo compatible"
            busqueda -> datos "Consulta passages_g con filtros y grupos"
            busqueda -> catalogo "Obtiene documentos en la misma g"
            catalogo -> datos "Lee documents_g"
            autoLayout lr
        }
        dynamic backend "D2-ConsultaRAG" "Sprint 2: BM25/RRF y LlamaIndex; IDs de referencias comprobados funcionalmente. Calidad en S3." {
            web -> api "Envía pregunta"
            api -> conversacion "Procesa turno"
            conversacion -> catalogo "Fija generación del turno"
            catalogo -> datos "Resuelve colecciones físicas"
            catalogo -> archivos "Lee configuración g"
            conversacion -> busqueda "Solicita contexto mediante adaptador"
            busqueda -> embeddings "Calcula vector denso"
            busqueda -> datos "Ejecuta denso + BM25 + RRF con filtros"
            busqueda -> catalogo "Hidrata documentos g"
            conversacion -> generacion "Entrega evidencia suficiente e IDs permitidos"
            generacion -> llm "Solicita síntesis con referencias"
            conversacion -> datos "Guarda turno e IDs del contexto"
            autoLayout lr
        }
        dynamic plataforma "D3-Evaluacion" "Sprint 3: todo el arnés, consultas, métricas e informes se prepara y ejecuta aquí." {
            responsable -> evaluacion "Prepara anotaciones y ejecuta evaluación"
            evaluacion -> archivos "Lee corpus y configuración congelados"
            evaluacion -> backend "Ejecuta las mismas consultas en tres modos"
            backend -> datos "Recupera IDs del corpus congelado"
            evaluacion -> llm "Evalúa respuestas cuando corresponda"
            evaluacion -> archivos "Guarda métricas por IDs, Hit@5 e informe"
            autoLayout lr
        }
        styles {
            element "Element" {
                shape RoundedBox
                background #2563eb
                color #ffffff
            }
            element "Person" {
                shape Person
                background #172554
            }
            element "Component" {
                background #dbeafe
                color #172554
            }
            element "Externo" {
                background #64748b
            }
            element "Frontend" {
                shape WebBrowser
            }
            element "BaseDatos" {
                shape Cylinder
                background #0f766e
            }
            element "Archivo" {
                shape Folder
                background #0f766e
            }
            element "ModeloLocal" {
                background #ede9fe
                color #4c1d95
            }
            element "Sprint2" {
                background #fef3c7
                color #78350f
            }
            element "Sprint3" {
                background #fce7f3
                color #831843
            }
            relationship "Relationship" {
                color #475569
                routing Orthogonal
            }
        }
    }
}
