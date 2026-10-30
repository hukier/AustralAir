# ADR-002: Seguridad Perimetral y Control de Acceso por Roles con Header X-API-Key

## Estado
Aceptado

## Contexto
El microservicio `servicio-reservas` actúa como puerta de entrada pública (API Gateway / Perímetro) para agencias de viaje, paneles internos de monitoreo y sistemas asociados. Sus rutas bajo `/v1` permiten tanto operaciones de consulta (`GET /v1/vuelos`, `GET /v1/pasajeros`, `GET /v1/reservas`) como operaciones críticas de mutación de estado e inventario (`POST /v1/pasajeros`, `POST /v1/reservas`, `DELETE /v1/reservas/{id}`).

Se requiere un mecanismo de autenticación y autorización perimetral (Requisito T6) que:
1. Rechace tráfico anónimo o con credenciales inválidas (`401 Unauthorized`).
2. Diferencie privilegios entre consumidores de solo consulta y operadores autorizados para emitir/anular reservas (`403 Forbidden`), aplicando el principio de mínimo privilegio.

## Alternativas Consideradas
1. **OAuth 2.0 / OpenID Connect (Keycloak / Auth0) con tokens JWT firmados (RS256):**
   - *Ventajas:* Identidad granular por usuario/agencia, expiración corta de tokens (`exp`), *scopes* estándar y revocación centralizada.
   - *Motivo de descarte:* Introduce un contenedor adicional de proveedor de identidad (IdP), gestión de certificados asimétricos y latencia de emisión de tokens desproporcionada para la integración B2B acotada del encargo.
2. **HTTP Basic Auth contra tabla de usuarios en `db-reservas`:**
   - *Ventajas:* Permite múltiples usuarios sin IdP externo.
   - *Motivo de descarte:* Exige hashing de contraseñas (bcrypt/argon2) y una consulta a base de datos en cada request, penalizando la latencia de rutas federadas como `GET /v1/vuelos`.
3. **Una única `X-API-Key` estática compartida sin roles:**
   - *Ventajas:* Implementación trivial.
   - *Motivo de descarte:* Carece de granularidad de autorización; un cliente de reportería o consulta tendría permisos para cancelar reservas o agotar el inventario de vuelos.
4. **Esquema `X-API-Key` en cabecera HTTP con separación de roles Operación y Lectura (Elegida):**
   - Validación en memoria en tiempo constante a partir de secretos inyectados por variables de entorno, distinguiendo explícitamente autenticación (`401`) de autorización (`403`).

## Decisión
Implementar autenticación y autorización perimetral obligatoria en todas las rutas `/v1/*` mediante la cabecera HTTP `X-API-Key` (declarada como `ApiKeyAuth` en `docs/openapi.yaml`), manteniendo únicamente `/health` público para orquestación de contenedores:

1. **Rol Operación (`API_KEY`):** Habilitado para ejecutar todos los métodos (`GET`, `POST`, `DELETE`).
2. **Rol Lectura (`API_KEY_LECTURA`):** Habilitado únicamente para métodos seguros de lectura (`GET`, `HEAD`, `OPTIONS`). Si intenta ejecutar `POST` o `DELETE`, la API rechaza la operación antes de tocar la base de datos o gRPC respondiendo **`HTTP 403 Forbidden`** con el esquema estándar `ErrorResponse` (`codigo: "PROHIBIDO"`).
3. **Credencial ausente o desconocida:** Responde **`HTTP 401 Unauthorized`** con `ErrorResponse` (`codigo: "NO_AUTORIZADO"`).

## Costo Aceptado
- **Gestión y rotación manual de secretos:** Al ser claves simétricas estáticas inyectadas por entorno (`.env`), rotar una clave comprometida requiere actualizar variables de entorno y reiniciar el contenedor `servicio-reservas`, además de no ofrecer trazabilidad individual por agente dentro de un mismo rol.
- **Exposición en transporte si no hay TLS externo:** En despliegues productivos fuera de localhost exige un proxy inverso con terminación HTTPS/TLS para evitar la interceptación de la cabecera `X-API-Key`.

## Consecuencias
- **Positivas:** Sobrecarga de validación despreciable (< 0.1 ms sin consultas adicionales a BD), separación clara entre `401 Unauthorized` y `403 Forbidden`, y protección efectiva del inventario frente a clientes de solo lectura.
- **Negativas:** Si el número de agencias externas crece con permisos diferenciados por ruta o cuota, será necesario migrar hacia JWT con *scopes* emitidos por un IdP dedicado.
