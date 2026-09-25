# ADR-002: Seguridad Perimetral Mediante Autenticación Estática con Header X-API-Key

## Estado
Aceptado

## Contexto
El microservicio `servicio-reservas` actúa como la puerta de entrada (API Gateway / Perímetro) para los clientes externos. Los endpoints como `GET /v1/vuelos` y `POST /v1/reservas` exponen datos comerciales e impactan directamente la disponibilidad de inventario.

Se requiere un mecanismo de autenticación para garantizar que únicamente consumidores autorizados puedan consumir la API REST, protegiendo el sistema de abusos y peticiones anónimas, sin introducir la sobrecarga operativa ni la latencia de un servidor de identidad externo (como OAuth2 o Keycloak) en esta etapa del proyecto.

## Decisión
Se decide implementar un esquema de autenticación perimetral estática mediante el encabezado HTTP:
```http
X-API-Key: secreto-australair-2026