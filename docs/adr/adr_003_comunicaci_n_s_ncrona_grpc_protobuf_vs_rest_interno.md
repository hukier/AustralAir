# ADR-003: Comunicación Interna Síncrona gRPC/Protobuf entre Microservicios

## Estado
Aceptado

## Contexto
El microservicio `servicio-reservas` debe coordinarse síncronamente con `servicio-asientos` para consultar disponibilidad de vuelos y reservar/liberar cupos en tiempo real durante la tramitación de una compra. 

Se evaluaron dos alternativas principales para la comunicación inter-servicio en la red privada:
1. **REST sobre HTTP/1.1 con payloads JSON:** Estándar, altamente legible, pero con sobrecosto de serialización/deserialización de strings, encabezados HTTP voluminosos y ausencia de tipado estricto a nivel de contrato.
2. **gRPC sobre HTTP/2 con Protocol Buffers (Protobuf):** Protocolo binario fuertemente tipado, con multiplexación de conexiones TCP y generación automática de stubs de cliente/servidor.

## Decisión
Se decide implementar **gRPC con Protocol Buffers** como el estándar de comunicación síncrona interna entre `servicio-reservas` y `servicio-asientos`.

- El contrato de comunicación se formaliza en el archivo `vuelos.proto`, definiendo servicios (`AsientosService`) y mensajes estructurados (`ListarVuelosRequest`, `ModificarCupoRequest`, etc.).
- Las bibliotecas `grpcio` y `grpcio-tools` se utilizan para compilar el contrato tanto en el servidor como en el cliente.
- El tráfico gRPC transcurre a través de la red interna `red-interna-grpc` en el puerto `50051`.

## Consecuencias

### Positivas
- **Eficiencia en serialización:** El formato binario de Protobuf reduce sustancialmente el tamaño de los paquetes transmitidos y el consumo de CPU al evitar el parseo de strings JSON.
- **Contrato fuertemente tipado:** El archivo `.proto` sirve como única fuente de verdad (Single Source of Truth), previniendo inconsistencias de tipos en tiempo de compilación/generación.
- **Multiplexación HTTP/2:** Múltiples solicitudes concurrentes entre microservicios pueden viajar sobre una única conexión TCP subyacente sin sufrir bloqueo de cabeza de línea (*head-of-line blocking* a nivel de aplicación).

### Negativas / Retos
- **Inspección de tráfico compleja:** Al ser binario, no es posible inspeccionar el tráfico directamente mediante herramientas básicas como `curl` convencional sin herramientas accesorias como `grpcurl`.
- **Acoplamiento temporal:** Al ser una comunicación síncrona RPC, `servicio-reservas` depende de la respuesta temporal de `servicio-asientos`, haciendo indispensable la configuración estricta de timeouts y manejo de fallos.