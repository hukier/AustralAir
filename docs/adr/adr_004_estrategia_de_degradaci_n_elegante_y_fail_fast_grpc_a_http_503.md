# ADR-004: Estrategia de Degradación Elegante y Mapeo de Excepciones gRPC a HTTP 503

## Estado
Aceptado

## Contexto
En una arquitectura distribuida, las dependencias de red pueden experimentar lentitud extrema, congestión o indisponibilidad física. Si el microservicio de Asientos sufre latencias elevadas (bloqueos en PostgreSQL o agotamiento de hilos), el cliente gRPC en el microservicio de Reservas podría quedar bloqueado en espera indefinida.

Este bloqueo saturaría el pool de conexiones de Uvicorn/FastAPI, provocando una falla en cascada que dejaría inoperante la API perimetral. Se requiere implementar un patrón de resiliencia que delimite el tiempo máximo de espera y preserve la disponibilidad del perímetro ante caídas parciales del ecosistema.

## Decisión
Se decide implementar el patrón **Fail-Fast** mediante un límite estricto de tiempo (*timeout*) en el cliente gRPC y una política unificada de mapeo de excepciones hacia la capa perimetral REST:

1. **Timeout determinista:** Cada llamada gRPC emitida desde `servicio-reservas` hacia `servicio-asientos` establece un timeout de **3.0 segundos** (`stub.ListarVuelos(..., timeout=3.0)`).
2. **Captura centralizada:** El cliente encapsula las llamadas en bloques de captura para `grpc.RpcError`.
3. **Mapeo a HTTP 503 con esquema estándar:** Si ocurre un error de tipo `grpc.StatusCode.DEADLINE_EXCEEDED` (timeout superado) o `grpc.StatusCode.UNAVAILABLE` (servicio de asientos apagado o inalcanzable), la API responde de inmediato con:
   - Código de estado: `HTTP 503 Service Unavailable`.
   - Payload JSON conforme al esquema `ErrorResponse` definido en `docs/openapi.yaml`:
     ```json
     {
       "codigo": "SERVICIO_NO_DISPONIBLE",
       "detalle": "El servicio interno de Asientos no se encuentra disponible o agotó el tiempo de espera.",
       "timestamp": "2026-09-25T14:53:27.912345Z"
     }
     ```

## Consecuencias

### Positivas
- **Prevención de fallas en cascada:** FastAPI libera sus recursos a los $3.0\,\text{s}$ exactos o de forma inmediata ante caídas de socket, manteniendo operativas rutas locales como la gestión de pasajeros.
- **Respuestas deterministas:** Los clientes externos reciben un error estructurado predecible en lugar de experimentar un cuelgue indefinido o un error genérico `500 Internal Server Error`.
- **Validación empírica:** El comportamiento fue comprobado en caliente deteniendo el contenedor de Asientos (`docker compose stop servicio-asientos`), obteniendo la respuesta `503` en milisegundos sin caída del servicio perimetral.

### Negativas / Retos
- **Peticiones legítimas abortadas:** Operaciones válidas que tomen más de 3 segundos debido a congestión transitoria serán canceladas para priorizar la estabilidad global.
- **Ausencia de reintentos con backoff:** Si la indisponibilidad es de solo unos milisegundos, la petición falla inmediatamente sin reintento automático (se sugiere implementar *Circuit Breaker* en futuras iteraciones).