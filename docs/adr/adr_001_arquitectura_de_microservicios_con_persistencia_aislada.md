# ADR-001: Adopción de Arquitectura de Microservicios con Bases de Datos Aisladas

## Estado
Aceptado

## Contexto
El sistema de reservas de vuelos AustralAir requiere gestionar dos capacidades operacionales críticas:
1. El ciclo de vida de las reservas (creación de orden, datos del pasajero, estado de confirmación).
2. El inventario atómico de asientos y disponibilidad por aeronave.

En un esquema de arquitectura monolítica tradicional con base de datos compartida, un pico de concurrencia en la consulta de disponibilidad o una transacción prolongada de actualización de inventario puede provocar contención de bloqueos (table locks / row locks), degradando el rendimiento de las operaciones de reserva. Asimismo, un fallo en el esquema o esquema relacional del inventario afectaría directamente al servicio de usuarios y reservas. Se requiere desacoplar ambos dominios para permitir escalabilidad independiente, aislamiento de fallos e interoperabilidad tecnológica.

## Decisión
Se decide adoptar un estilo arquitectónico de **Microservicios** dividiendo el sistema en dos servicios desacoplados:
- **`servicio-reservas`**: Responsable de la lógica de negocio perimetral, gestión de órdenes de reserva y exposición de la API REST externa.
- **`servicio-asientos`**: Responsable exclusivo de la persistencia, consulta y mutación atómica del cupo de asientos por vuelo.

Cada microservicio dispone de su propia instancia de base de datos **PostgreSQL** completamente aislada a nivel de proceso y almacenamiento (patrón *Database-per-Service*):
- `db-reservas`: Almacena exclusivamente tablas del dominio de reservas.
- `db-asientos`: Almacena exclusivamente tablas del catálogo de vuelos y cupos disponibles.

El acceso directo entre la base de datos de un microservicio y el código del otro está estrictamente prohibido a nivel de segmentación de red Docker. Cualquier interacción entre dominios se canaliza a través de contratos de interfaz explícitos.

## Consecuencias

### Positivas
- **Aislamiento de fallos:** Un bloqueo de transacciones o caída en `db-asientos` no corrompe ni bloquea directamente las conexiones de `db-reservas`.
- **Evolución independiente:** Las tablas y esquemas de inventario pueden optimizarse (por ejemplo, índices compuestos o particionamiento) sin requerir re-despliegue del servicio de reservas.
- **Escalabilidad horizontal selectiva:** Si la consulta de vuelos sufre alta demanda estacional, `servicio-asientos` puede escalar de forma diferenciada respecto a `servicio-reservas`.
- **Integridad local reforzada:** Permite aplicar cláusulas SQL atómicas (`WHERE asientos_disponibles >= $cantidad`) directamente en el motor relacional de inventario.

### Negativas / Retos
- **Consistencia eventual y orquestación:** No es posible utilizar transacciones distribuidas ACID nativas (Two-Phase Commit). La compensación de reservas canceladas requiere llamadas explícitas de liberación de cupo.
- **Sobrecosto operacional:** Aumento en el uso de memoria RAM y CPU al desplegar dos contenedores PostgreSQL independientes y gestionar dos cadenas de conexión y migraciones separadas.