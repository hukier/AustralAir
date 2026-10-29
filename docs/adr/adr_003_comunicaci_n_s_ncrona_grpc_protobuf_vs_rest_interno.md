# ADR-003: Comunicación Interna Síncrona gRPC/Protobuf entre Microservicios

## Estado
Aceptado

## Contexto
El microservicio perimetral `servicio-reservas` debe interactuar de forma continua con `servicio-asientos` para consultar disponibilidad de itinerarios y mutar cupos transaccionalmente. Esta interacción ocurre en la red interna de contenedores y requiere alto rendimiento, tipado estricto y baja sobrecarga computacional.

## Alternativas Consideradas
1. **REST interno sobre HTTP/1.1 con JSON:** Estándar convencional, pero penalizado por la sobrecarga de serialización/deserialización de texto plano y la apertura repetitiva de conexiones TCP sin multiplexación nativa.
2. **Colas asíncronas de mensajes (AMQP / RabbitMQ):** Ideal para eventos eventuales, pero introduce latencia no deseada para consultas síncronas de inventario donde el cliente web aguarda confirmación inmediata.
3. **gRPC con Streaming (Server/Bidirectional Streaming):** Mantiene canales abiertos continuos enviando flujos de mensajes.
4. **gRPC Unario (Request-Response sobre HTTP/2) (Elegida):** Invocación síncrona tradicional donde cada petición envía un mensaje y recibe una única respuesta.

## Decisión
Adoptar **gRPC sobre HTTP/2 con Protocol Buffers** utilizando exclusivamente el modo de invocación **Unario (Unary RPC)** para todas las operaciones (`ConsultarVuelo`, `ListarVuelos`, `ReservarAsiento`, `LiberarAsiento`).

### Justificación del Modo Unario frente a Streaming (Requisito T4)
* **Alineación con el Dominio:** Las operaciones de reserva y consulta son atómicas y discretas: se solicita un vuelo específico o una mutación de cupo y se espera una confirmación binaria inmediata (`éxito / fallo`). El patrón petición-respuesta clásico mapea de forma natural 1:1 con las peticiones entrantes del API Gateway REST.
* **Simplicidad Operativa y Manejo de Timeouts:** En RPCs unarios, los límites de tiempo (*timeouts / deadlines*) son deterministas: el cliente fija 3.0 s y, si no hay respuesta, el canal corta con `DEADLINE_EXCEEDED`. En streaming, detectar estancamientos en flujos infinitos requiere *heartbeats* y lógica adicional de reconexión.
* **Sobrecarga de Recursos Innecesaria:** Mantener streams de larga duración o canales bidireccionales abiertos entre contenedores consumiría descriptores de archivo y memoria en el pool de hilos para operaciones que se ejecutan y concluyen en milisegundos.

## Costo Aceptado
* El tráfico interno en formato binario no es inspeccionable con herramientas tradicionales de depuración HTTP como `curl`, requiriendo utilidades específicas como `grpcurl` o stubs de prueba.
* Acoplamiento a nivel de compilación: cualquier cambio en `vuelos.proto` exige recompilar los stubs en ambos microservicios.

## Consecuencias
* **Positivas:** Reducción drástica del tamaño de los mensajes y consumo de CPU, multiplexación de múltiples llamadas sobre una misma conexión TCP y contratos estáticos que impiden errores de tipeo.
* **Negativas:** Obliga a gestionar explícitamente políticas de timeout y manejo de excepciones de red en el cliente perimetral.