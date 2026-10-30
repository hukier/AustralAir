# ADR-001: Adopción de Arquitectura de Microservicios con Bases de Datos Aisladas

## Estado
Aceptado

## Contexto
El sistema de reservas de vuelos AustralAir debe resolver de manera concurrente dos problemas operacionales con exigencias distintas:
1. **Gestión comercial de reservas y pasajeros:** exposición de API REST pública, validación de entrada, autenticación/autorización por roles e idempotencia ante reintentos de agencias externas.
2. **Control atómico del inventario físico de asientos:** evitar que dos agencias vendan el mismo último asiento disponible o que cancelaciones concurrentes liberen cupos duplicados provocando sobreventa.

Se requiere definir la frontera de descomposición de servicios y su estrategia de persistencia cumpliendo el aislamiento de datos (Requisito T5) y manteniendo coherencia ante fallas parciales.

## Alternativas Consideradas
1. **Monolito modular con base de datos única:**
   - *Ventajas:* Transacciones ACID locales simples (`BEGIN ... COMMIT` abarcando `vuelos` y `reservas` en un mismo motor PostgreSQL) y menor sobrecosto operativo.
   - *Motivo de descarte:* Acopla el ciclo de despliegue y escalamiento del catálogo/inventario interno con la API perimetral expuesta a clientes externos; un bloqueo pesado en inventario impacta directamente el registro y consulta de pasajeros.
2. **Dos microservicios compartiendo una misma base de datos PostgreSQL:**
   - *Ventajas:* Evita llamadas RPC para cruzar reservas con vuelos.
   - *Motivo de descarte:* Viola el principio de autonomía de microservicios y el Requisito T5; cualquier cambio de esquema en `vuelos` rompe silenciosamente a `servicio-reservas` y persiste un único punto de contención transaccional.
3. **Dos microservicios con persistencia aislada (*Database-per-Service*) y segmentación de red (Elegida):**
   - `servicio-reservas` con `db-reservas` (`red-reservas`) y `servicio-asientos` con `db-asientos` (`red-asientos`), comunicados exclusivamente vía gRPC sobre `red-backend`.

## Decisión
Adoptar dos microservicios autónomos con instancias PostgreSQL independientes y redes Docker aisladas:
- **`servicio-reservas` (`db-reservas`):** Administra `pasajeros`, `reservas` e `idempotency_keys`.
- **`servicio-asientos` (`db-asientos`):** Administra exclusivamente la tabla `vuelos` y sus mutaciones atómicas de cupo (`ReservarAsiento`, `LiberarAsiento`).

### Datos referenciados entre fronteras y consistencia sin 2PC
- `servicio-reservas` **solo almacena `vuelo_id` (`VARCHAR(50)`) como referencia lógica** sin clave foránea física, evitando duplicar `origen`, `destino`, `codigo` o `asientos_disponibles` (que quedarían obsoletos frente a ventas concurrentes). La lectura del catálogo (`GET /v1/vuelos`) se resuelve por consulta federada vía gRPC.
- Al no existir transacciones distribuidas ACID (2PC), la coherencia se protege mediante:
  1. **Reserva previa de `Idempotency-Key` en BD** asociada al hash SHA-256 del cuerpo antes de invocar gRPC.
  2. **Compensación explícita ( patrón Saga/Compensating Action):** si `ReservarAsiento` descuenta el cupo en `Asientos` pero falla el `COMMIT` local en `db-reservas`, `servicio-reservas` ejecuta inmediatamente `LiberarAsiento` para restituir el asiento antes de responder error.
  3. **Cancelación condicional atómica:** `UPDATE reservas SET estado = 'CANCELADA' WHERE id = :id AND estado = 'CONFIRMADA'` garantiza que ante múltiples `DELETE` simultáneos solo una petición invoque `LiberarAsiento`; si gRPC falla (`503`), se ejecuta `ROLLBACK` manteniendo la reserva `CONFIRMADA`.
  4. **Verificación activa de deadline en `Asientos`:** `context.is_active()` revierte (`rollback`) el descuento si el cliente gRPC ya cortó por timeout antes del commit.

## Costo Aceptado
- **Sobrecosto de infraestructura y latencia interna:** Desplegar dos motores PostgreSQL independientes incrementa el uso de memoria/CPU y añade un salto de red gRPC por cada emisión o cancelación de reserva.
- **Complejidad de compensación:** La aplicación debe encargarse explícitamente de revertir cupos ante fallas locales y existe una ventana residual inherente a redes asíncronas si una conexión cae justo después del `COMMIT` en `Asientos` y antes de recibir confirmación en `Reservas`.

## Consecuencias
- **Positivas:** Aislamiento real de fallos (si `Asientos` cae, `GET/POST /v1/pasajeros` y `GET /v1/reservas` siguen operativos), cumplimiento estricto de fronteras DDD/T5 y prevención de sobreventa tanto en reservas como en cancelaciones concurrentes.
- **Negativas:** Mayor complejidad de pruebas de integración al requerir verificar flujos concurrentes y fallas parciales entre contenedores.
