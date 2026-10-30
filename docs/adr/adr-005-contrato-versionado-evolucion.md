# ADR-005: Estrategia de Contratos, Versionado y Evolución de APIs (D3)

## Estado
Aceptado

## Contexto
El sistema AustralAir desacopla la atención perimetral (`servicio-reservas`) de la gestión de inventario (`servicio-asientos`) mediante dos contratos formales explícitos (Requisito T3):
1. **Contrato externo REST:** especificado en `docs/openapi.yaml` (OpenAPI 3.0.3) y expuesto bajo `/v1`.
2. **Contrato interno RPC:** especificado en una única fuente de verdad `/proto/vuelos.proto` (Protocol Buffers `proto3`) bajo `package austral.airasientos.v1`.

En sistemas distribuidos, los esquemas evolucionan continuamente (incorporación de puerta de embarque, tarifas dinámicas, equipaje o retiro de campos obsoletos). Sin reglas claras de versionado y compatibilidad, un cambio en `vuelos.proto` o en `openapi.yaml` puede corromper la deserialización binaria entre microservicios o romper integraciones activas de agencias externas.

## Alternativas Consideradas
1. **Evolución sin versionado explícito (*Code-First* implícito):**
   - *Motivo de descarte:* Modificar modelos Pydantic o mensajes Protobuf directamente sin prefijo de versión impide coexistencia entre clientes antiguos y nuevos, generando fallas silenciosas en tiempo de ejecución.
2. **Versionado por cabeceras de negociación de contenido (`Accept: application/vnd.australair.v1+json`):**
   - *Motivo de descarte:* Dificulta la exploración directa desde navegadores/clientes simples, complica el cacheo por URL y no aplica de manera homogénea a paquetes gRPC.
3. **Versionado explícito por ruta (`/v1`) + paquete Protobuf (`austral.airasientos.v1`) con fuente única del `.proto` (Elegida):**
   - Hace visible la versión mayor en cada endpoint y nombre de servicio gRPC (`/austral.airasientos.v1.AsientosService/...`), compilando los stubs desde `/proto/vuelos.proto` durante el build de Docker de ambos contenedores para impedir deriva de contratos.

## Decisión
Adoptar una política estricta de compatibilidad hacia atrás (*backward*) y hacia adelante (*forward*) para cambios menores dentro de `v1`, reservando `v2` únicamente para cambios incompatibles (*breaking changes*):

### 1. Reglas de Evolución en Protocol Buffers (`/proto/vuelos.proto`)
- **Fuente única de verdad:** Prohibido duplicar `vuelos.proto` dentro de subcarpetas de servicios; ambos `Dockerfile` compilan sus stubs desde `/proto/vuelos.proto`.
- **Cambios compatibles (mantienen `v1`):**
  - Agregar nuevos campos opcionales con un **número de tag nuevo y nunca antes usado** (ej. agregar `string puerta_embarque = 7;` en `VueloResponse`). Un cliente compilado con la versión previa ignora los tags desconocidos sin fallar; un cliente nuevo recibe el valor por defecto (`""` o `0`) si habla con un servidor previo.
  - Agregar nuevos métodos RPC al servicio `AsientosService` o nuevos valores al final de `enum CodigoError` (conservando `0` como valor no especificado por defecto).
- **Eliminación segura de campos (`reserved`):**
  - Nunca reutilizar un número de tag ni el nombre de un campo eliminado, pues causaría corrupción de tipos en el formato binario *wire*. Al retirar un campo se debe bloquear con `reserved`:
    ```protobuf
    message VueloResponse {
      reserved 4;
      reserved "destino";
      // ...
    }
    ```
- **Cambios incompatibles (*Breaking Changes* $\rightarrow$ requieren `austral.airasientos.v2`):**
  - Cambiar el tipo de dato de un campo existente (ej. `string vuelo_id` a `int64` o tipos incompatibles en el *wire format*), cambiar números de tag existentes, o alterar la semántica obligatoria de un RPC existente. En tal caso se crea `proto/v2/vuelos.proto` con `package austral.airasientos.v2` y el servidor expone temporalmente `v1` y `v2` en paralelo hasta migrar a todos los clientes internos.

### 2. Reglas de Evolución en la API REST (`docs/openapi.yaml`) y Aviso a Consumidores
- **Cambios compatibles en `/v1`:** Añadir campos opcionales en respuestas JSON, nuevas rutas o nuevos parámetros opcionales de consulta/cabecera (como `Idempotency-Key`).
- **Cambios incompatibles ($\rightarrow$ `/v2`):** Eliminar o renombrar propiedades existentes del JSON de respuesta, volver obligatorio un campo antes opcional en el request, o cambiar el esquema unificado `ErrorResponse` (`{codigo, detalle, timestamp}`).
- **Protocolo de comunicación a consumidores externos:**
  1. Actualización versionada de `docs/openapi.yaml` y publicación de notas de cambio (*Changelog*) en el repositorio antes del despliegue.
  2. Durante el período de transición previa al retiro de un endpoint o versión `/v1`, emisión de cabeceras HTTP estándar `Deprecation: true` y `Sunset: <fecha HTTP>` junto con coexistencia simultánea de `/v1` y `/v2` para otorgar ventana de migración a las agencias.

## Costo Aceptado
- **Mantenimiento temporal de dos versiones (`v1` y `v2`):** Ante un cambio incompatible es necesario mantener y probar ambos controladores REST o servicers gRPC durante la ventana de depreciación.
- **Disciplina de revisión de contratos:** Prohibir la reutilización de tags y exigir `reserved` acumula metadatos históricos en `vuelos.proto`, requiriendo revisión explícita en cada Pull Request que toque `/proto` o `docs/openapi.yaml`.

## Consecuencias
- **Positivas:** Despliegues independientes entre `servicio-asientos` y `servicio-reservas` ante extensiones aditivas sin caídas por incompatibilidad binaria, eliminación total de copias divergentes del `.proto` y previsibilidad para agencias consumidoras de la API REST.
- **Negativas:** Los cambios estructurales profundos en el modelo de dominio no pueden aplicarse in-situ y exigen orquestar migración hacia una nueva versión mayor.
