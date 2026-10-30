# ADR-004: Estrategia de Degradación Elegante, Fail-Fast y Manejo de Timeouts (gRPC a HTTP 503)

## Estado
Aceptado

## Contexto
En una arquitectura distribuida, el servicio interno `servicio-asientos` o su base de datos `db-asientos` pueden experimentar caídas de contenedor, particiones de red o lentitud severa (por ejemplo, bloqueos de fila prolongados en PostgreSQL). Si `servicio-reservas` realiza llamadas gRPC sin cota temporal estricta, los trabajadores de FastAPI/Uvicorn quedarían bloqueados indefinidamente provocando agotamiento de hilos y una falla en cascada sobre rutas locales que no dependen de `Asientos`.

Adicionalmente, cuando una llamada de mutación (`ReservarAsiento`) expira por *timeout*, la red no garantiza por sí sola si el servidor interno alcanzó o no a descontar el asiento, lo que exige coordinar el tiempo límite del cliente con guardas transaccionales en el servidor.

## Alternativas Consideradas
1. **Llamadas síncronas sin timeout explícito (timeout por defecto de socket TCP):**
   - *Motivo de descarte:* Las peticiones quedan colgadas durante decenas de segundos o minutos, saturando el pool de conexiones de `servicio-reservas` e inutilizando incluso endpoints locales (`/v1/pasajeros`).
2. **Reintentos automáticos inmediatos en el API Gateway ante `DEADLINE_EXCEEDED`:**
   - *Motivo de descarte:* En escenarios de congestión o bloqueo de BD multiplica la carga sobre el backend degradado (*retry storm*) y, en operaciones no idempotentes de descuento por cantidad, arriesga descontar múltiples asientos para una sola solicitud.
3. **Patrón Fail-Fast con deadline gRPC de 3.0 s, cabecera `Retry-After` y aborto transaccional en destino (Elegida):**
   - Acota determinísticamente el tiempo máximo de bloqueo en el perímetro, informa al cliente cuándo reintentar y verifica la vigencia del contexto gRPC en `Asientos` antes de confirmar cambios en BD.

## Decisión
1. **Deadline estricto de 3.0 segundos:** Toda invocación en `AsientosGRPCClient` fija `timeout=3.0`.
2. **Traducción uniforme a `HTTP 503 Service Unavailable` con `Retry-After`:** Ante `grpc.StatusCode.UNAVAILABLE` o `grpc.StatusCode.DEADLINE_EXCEEDED`, `servicio-reservas` responde `503` con el esquema oficial `ErrorResponse` (`codigo: "SERVICIO_NO_DISPONIBLE"`) e incluye la cabecera HTTP `Retry-After: 5` para guiar el *backoff* del consumidor externo.
3. **Protección de consistencia ante lentitud y fallos:**
   - En `servicio-asientos`, antes de abrir transacción tras latencias y nuevamente después del `UPDATE` pero **antes** de `conn.commit()`, se evalúa `if not context.is_active(): conn.rollback()`. Así, si una fila estuvo bloqueada más de 3.0 s y el cliente ya cortó por `DEADLINE_EXCEEDED`, el descuento se revierte automáticamente sin dejar asientos huérfanos.
   - En `servicio-reservas`, si `ReservarAsiento` retorna éxito pero falla la persistencia local en `db-reservas`, se ejecuta `ROLLBACK` local seguido de una llamada compensatoria `LiberarAsiento(vuelo_id, 1)`. Si falla `LiberarAsiento` durante una cancelación, se hace `ROLLBACK` en `db-reservas` conservando el estado `CONFIRMADA`.

## Costo Aceptado
- **Latencia de detección en reconexión del canal gRPC:** Cuando `servicio-asientos` se detiene abruptamente, la primera petición sobre el socket roto suele fallar rápido (~40 ms con `UNAVAILABLE`), pero las peticiones subsiguientes mientras el canal HTTP/2 intenta reconectar pueden esperar hasta agotar el deadline de `3.0 s` antes de responder `503`.
- **Ventana residual sin 2PC:** Dado que `ModificarCupoRequest` opera por `vuelo_id` y `cantidad` (sin persistir `reserva_id` en `db-asientos`), `servicio-reservas` **no** puede invocar `LiberarAsiento` a ciegas tras un `DEADLINE_EXCEEDED` porque liberaría un cupo ajeno si `Asientos` ya había hecho `rollback`. Aunque `context.is_active()` cubre bloqueos previos al `commit`, persiste una ventana microscópica si el corte de red ocurre exactamente después de `conn.commit()` en `Asientos`.

## Consecuencias
- **Positivas:** Aislamiento comprobado de fallas parciales (los endpoints locales `GET/POST /v1/pasajeros` y `GET /v1/reservas` continúan respondiendo en pocos milisegundos con `Asientos` caído o lento), contrato de error homogéneo con `Retry-After: 5` y eliminación de pérdida de asientos ante bloqueos de base de datos superiores al timeout.
- **Negativas:** Operaciones legítimas cuya ejecución supere puntualmente los 3.0 s son rechazadas con `503`, delegando el reintento seguro al cliente mediante `Idempotency-Key`.
