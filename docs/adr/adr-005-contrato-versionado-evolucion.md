# ADR-005: Estrategia de Contratos, Versionado y Evolución de APIs

## Estado
Aceptado

## Contexto
El sistema AustralAir desacopla la atención perimetral (`servicio-reservas`) de la gestión de inventario (`servicio-asientos`) mediante dos fronteras de comunicación: una API REST pública consumida por clientes externos y un contrato RPC interno basado en Protocol Buffers (`vuelos.proto`). 

En sistemas distribuidos, los esquemas de datos evolucionan con frecuencia (adición de aeropuertos, puertas de embarque, tarifas o cambios en políticas de equipaje). Sin una política explícita de compatibilidad y versionado:
1. Cambios en el archivo `.proto` pueden romper la deserialización binaria en clientes desactualizados.
2. Modificaciones en la API REST perimetral pueden invalidar aplicaciones móviles o integraciones de agencias asociadas.
3. No existe un protocolo documentado para depreciar o retirar campos obsoletos.

## Alternativas Consideradas
1. **Contrato sin versionado (Code-First):** Generar esquemas dinámicamente a partir de clases de Python. Se descarta por el riesgo de inducir incompatibilidades silenciosas en producción y carecer de control estricto de tipos.
2. **Versionado por cabeceras HTTP (Content Negotiation) en REST:** Utilizar `Accept: application/vnd.australair.v1+json`. Aunque es RESTful puro, incrementa la complejidad de consumo para clientes web y no resuelve el versionado de la capa gRPC.
3. **Versionado semántico dual en URL y Package (Estrategia Elegida):** Prefijar rutas REST con `/v1` y estructurar Protocol Buffers bajo el paquete canónico `austral.airasientos.v1`.

## Decisión
Adoptar una estrategia formal de evolución hacia adelante (*forward compatibility*) y hacia atrás (*backward compatibility*) gobernada por las siguientes reglas:

### 1. Evolución del Contrato gRPC / Protocol Buffers (`vuelos.proto`)
* **Regla de Adición Compatible:** Nuevos campos (por ejemplo, `string puerta_embarque = 7;`) solo pueden añadirse como campos opcionales con un nuevo número de tag secuencial. Los clientes que utilicen stubs compilados con versiones previas ignorarán el nuevo tag sin fallar.
* **Regla de Eliminación y Depreciación:** Prohibido reutilizar números de tag o nombres de campos eliminados. Se debe utilizar la palabra clave `reserved`:
  ```protobuf
  // Si se retira el campo destino
  reserved 4;
  reserved "destino";