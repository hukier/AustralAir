# AustralAir - Sistema Distribuido de Reservas e Inventario de Vuelos

Plataforma de reservas de vuelos e inventario atómico de asientos construida sobre una arquitectura de microservicios orientada a resiliencia, persistencia aislada (*Database-per-Service*) y comunicación interna de alto rendimiento mediante gRPC.

---

## 1. Arquitectura General del Sistema

El sistema implementa dos microservicios autónomos desplegados en contenedores Docker y segmentados en redes virtuales aisladas:

- **`servicio-reservas` (API Gateway / Perímetro):**
  * Expone API REST pública en el puerto `8000` bajo el prefijo versionado `/v1`.
  * Autenticación y autorización por roles mediante cabecera HTTP `X-API-Key` (`API_KEY` con rol **Operación** y `API_KEY_LECTURA` con rol **Lectura**, respondiendo `401` o `403` según corresponda — ADR-002).
  * Base de datos relacional independiente: `db-reservas` (PostgreSQL en puerto interno `5432`). Gestiona tablas `pasajeros`, `reservas` e `idempotency_keys` (con hash SHA-256 del cuerpo y compensación ante fallos locales).
  * Actúa como cliente gRPC consumiendo las capacidades del catálogo de asientos.
  * Implementa patrón **Fail-Fast** con timeout estricto de 3.0 segundos y degradación controlada retornando `HTTP 503 Service Unavailable` estructurado con cabecera `Retry-After: 5` (ADR-004).
  * Documentación interactiva Swagger/OpenAPI disponible en `http://localhost:8000/docs`.

- **`servicio-asientos` (Backend de Inventario):**
  * Expone servicios RPC vía **gRPC / Protocol Buffers** en el puerto `50051` utilizando un canal unario sobre HTTP/2 (ADR-003).
  * Contrato de interfaz binaria único centralizado en la raíz del repositorio (`/proto/vuelos.proto`) bajo el paquete `austral.airasientos.v1` (ADR-005).
  * Base de datos relacional independiente: `db-asientos` (PostgreSQL en puerto interno `5432`). Gestiona la tabla `vuelos`.
  * Garantiza transaccionalidad atómica y previene sobreventas concurrentes mediante actualización SQL condicional (`WHERE vuelo_id = %s AND asientos_disponibles >= %s`).
  * Guarda explícita en devoluciones que rechaza exceder la capacidad física de la aeronave (`(asientos_disponibles + %s) <= capacidad_total`), evitando enmascarar errores de doble liberación.
  * Detección activa de timeout o cancelación gRPC (`context.is_active()`) antes del commit para evitar asientos descontados sin reserva en el cliente.

---

## 2. Prerrequisitos y Configuración

- **Docker Engine v24.0+** y **Docker Compose v2+** en ejecución.
- **Python 3.10+** en el equipo anfitrión para ejecutar las rutinas de benchmarking.
- Dependencias estándar de Python para medición (`urllib` nativo; `numpy` opcional para cálculo de percentiles).

### Configuración de Variables de Entorno y Secretos (`.env`)

Docker Compose utiliza el archivo `.env` en la raíz del proyecto para inyectar credenciales y puertos. Genere este archivo a partir de la plantilla incluida:

- **En Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```

- **En Linux / WSL / macOS:**
  ```bash
  cp .env.example .env  # clona el ejemplo al archivo .env
  ```

Antes de iniciar los servicios, revise y ajuste los valores de `.env` según su entorno. El despliegue aplica validación estricta de estas variables en `docker-compose.yml` mediante el patrón `${VAR:?msg}`:

```dotenv
ASIENTOS_DB_USER=user_asientos
ASIENTOS_DB_PASSWORD=asientos_secret_pass_2026
ASIENTOS_DB_NAME=asientos_db

RESERVAS_DB_USER=user_reservas
RESERVAS_DB_PASSWORD=reservas_secret_pass_2026
RESERVAS_DB_NAME=reservas_db

API_KEY=secreto-australair-2026
API_KEY_LECTURA=lectura-australair-2026
```

---

## 3. Puesta en Marcha (Despliegue)

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/tu-usuario/AustralAir.git
   cd AustralAir
   ```

2. **Construir y levantar todos los contenedores:**
   ```bash
   docker compose up -d --build
   ```

3. **Verificar el estado de los servicios:**
   ```bash
   docker compose ps
   ```

   Los cuatro contenedores deben reportar estado activo y saludable (healthy):
   * `australair-reservas` (`healthy`)
   * `australair-asientos` (`healthy`)
   * `australair-db-reservas` (`healthy`)
   * `australair-db-asientos` (`healthy`)

---

## 4. Endpoints de la API REST (`servicio-reservas`)

La documentación OpenAPI interactiva se encuentra habilitada en `http://localhost:8000/docs`. Todas las rutas bajo `/v1` requieren el encabezado de autenticación perimetral (`secreto-australair-2026` para rol **Operación** con lectura/escritura, o `lectura-australair-2026` para rol **Lectura** exclusivo en `GET`, devolviendo `403 Forbidden` en `POST`/`DELETE`):

```http
X-API-Key: secreto-australair-2026
```

### Tabla de Rutas Principales:

| Método | Endpoint | Descripción | Parámetros / Payload Requerido |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Chequeo de salud del gateway (público) | Ninguno |
| `GET` | `/v1/vuelos` | Consulta catálogo de vuelos vía gRPC | `X-API-Key` |
| `POST` | `/v1/pasajeros` | Registra un nuevo pasajero | `X-API-Key, {"rut": "18945632-1", "nombre_completo": "...", "email": "..."}` |
| `POST` | `/v1/reservas` | Crea reserva con soporte de idempotencia | `X-API-Key`, Idempotency-Key (opcional), `{"pasajero_id": "UUID", "vuelo_id": "1"}` |
| `GET` | `/v1/reservas/{id}` | Consulta el estado de una reserva | `X-API-Key`, parámetro `id (UUID)` en URL |
| `DELETE` | `/v1/reservas/{id}` | Cancelación atómica y restitución de cupo | `X-API-Key`, parámetro `id (UUID)` en URL |


### Pruebas directas con `curl`:

* **Consultar catálogo de vuelos disponibles:**
  ```bash
  curl -i -H "X-API-Key: secreto-australair-2026" http://localhost:8000/v1/vuelos
  ```

* **Registrar un pasajero:**
  ```bash
  curl -i -X POST http://localhost:8000/v1/pasajeros \
    -H "X-API-Key: secreto-australair-2026" \
    -H "Content-Type: application/json" \
    -d '{"rut": "18945632-1", "nombre_completo": "Camila Soto", "email": "camila.soto@email.com"}'
  ```

---

## 5. Verificación Funcional y Modo de Falla (T7)

### A. Prueba de Degradación Controlada y Resiliencia (Requisito T7)

Comprueba que ante la pérdida total de conectividad con el microservicio interno de Asientos, el API Gateway intercepta el error gRPC de inmediato y entrega una respuesta HTTP 503 estandarizada sin colapsar el proceso principal:

1. **Detener el contenedor del backend:**
   ```bash
   docker compose stop servicio-asientos
   ```

2. **Ejecutar la consulta perimetral:**
   ```bash
   curl -i -H "X-API-Key: secreto-australair-2026" http://localhost:8000/v1/vuelos
   ```

   **Respuesta esperada:** Código de estado `HTTP/1.1 503 Service Unavailable` con cuerpo JSON conforme al esquema de error:
   ```json
   {
     "codigo": "SERVICIO_NO_DISPONIBLE",
     "detalle": "El servicio interno de Asientos no se encuentra disponible o agotó el tiempo de espera.",
     "timestamp": "2026-09-25T14:53:27.912345Z"
   }
   ```

3. **Reanudar el contenedor:**
   ```bash
   docker compose start servicio-asientos
   ```

### B. Batería de Pruebas Unitarias / Integración de Asientos

Para ejecutar los 8 casos de prueba con aserciones formales sobre el microservicio de asientos:

```bash
docker compose exec servicio-asientos python test_client.py
```
Nota de Aislamiento: La batería opera sobre un vuelo temporal de prueba (`TEST-99`, capacidad 10) que se inicializa y destruye automáticamente en un bloque `finally`, preservando intacto el inventario de los vuelos reales (`AU-102` y `AU-205`).
---

## 6. Experimento de Ingeniería ABET 6: Evaluación Bajo Degradación

El experimento evalúa el comportamiento del API Gateway ante retardos sintéticos inyectados en las llamadas gRPC de `servicio-asientos` mediante la variable de entorno `LATENCIA_SIMULADA`. El script `medir_abet6.py` implementa:
* 3 repeticiones consecutivas de 100 peticiones con concurrencia 10 ($C=10$) y fase previa de calentamiento (warm-up).
* Persistencia automática de cada muestra individual en `resultados_abet6_crudos.csv` para verificación empírica y análisis de variabilidad.
* Soporte para consultas (`GET /v1/vuelos`) y creación de reservas (`POST /v1/reservas`).

### Protocolo de Ejecución de los 4 Escenarios:

#### En entornos Windows (PowerShell):
```bash
# Escenario 1: Base (0.0 s de retardo)
$env:LATENCIA_SIMULADA="0.0"; docker compose up -d servicio-asientos
python medir_abet6.py "Escenario 1: Base" GET

# Escenario 2: Degradación Moderada (0.5 s de retardo)
$env:LATENCIA_SIMULADA="0.5"; docker compose up -d servicio-asientos
python medir_abet6.py "Escenario 2: Moderado" GET

# Escenario 3: Límite Operacional (2.5 s de retardo)
$env:LATENCIA_SIMULADA="2.5"; docker compose up -d servicio-asientos
python medir_abet6.py "Escenario 3: Limite" GET

# Escenario 4: Fail-Fast y Timeout (4.0 s de retardo)
$env:LATENCIA_SIMULADA="4.0"; docker compose up -d servicio-asientos
python medir_abet6.py "Escenario 4: Fail-Fast" GET
python medir_abet6.py "Escenario 4: Fail-Fast" POST
```

#### En entornos Linux / WSL / macOS:
```bash
# Escenario 1: Base (0.0 s de retardo)
LATENCIA_SIMULADA=0.0 docker compose up -d servicio-asientos
python3 medir_abet6.py "Escenario 1: Base" GET

# Escenario 2: Degradación Moderada (0.5 s de retardo)
LATENCIA_SIMULADA=0.5 docker compose up -d servicio-asientos
python3 medir_abet6.py "Escenario 2: Moderado" GET

# Escenario 3: Límite Operacional (2.5 s de retardo)
LATENCIA_SIMULADA=2.5 docker compose up -d servicio-asientos
python3 medir_abet6.py "Escenario 3: Limite" GET

# Escenario 4: Fail-Fast y Timeout (4.0 s de retardo)
LATENCIA_SIMULADA=4.0 docker compose up -d servicio-asientos
python3 medir_abet6.py "Escenario 4: Fail-Fast" GET
python3 medir_abet6.py "Escenario 4: Fail-Fast" POST
```
Al finalizar las mediciones, restablecer el backend a su régimen nominal:
```bash
# En Windows (PowerShell):
$env:LATENCIA_SIMULADA="0.0"; docker compose up -d servicio-asientos
# En Linux / macOS (Bash):
LATENCIA_SIMULADA=0.0 docker compose up -d servicio-asientos
```

### Resultados Empíricos Registrados:

| Escenario | Retardo Inyectado | Throughput | Latencia $p50$ | Latencia $p95$ | Latencia $p99$ | Distribución HTTP |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Base** | 0.0 s | ~57.3 req/s | ~133.2 ms | ~260.0 ms | ~289.4 ms | 100% 200 OK |
| **2. Moderado** | 0.5 s | ~16.5 req/s | ~535.1 ms | ~1196.0 ms | ~1211.4 ms | 100% 200 OK |
| **3. Límite** | 2.5 s | ~3.9 req/s | ~2527.8 ms | ~2931.7 ms | ~2944.6 ms | 100% 200 OK |
| **4. Fail-Fast** | 4.0 s | ~3.3 req/s | ~3023.2 ms | ~3050.5 ms | ~3057.4 ms | 100% 503 Unavailable |

> **Conclusión técnica:** Al superar el umbral de 3.0 s en el Escenario 4, el cliente gRPC interrumpe la conexión de forma determinista a los $\approx 3.02\,\text{s}$ ($p50$), propagando inmediatamente HTTP 503 y liberando los hilos del API Gateway para preservar la atención de rutas perimetrales no degradadas.

---

## 7. Registros de Decisión Arquitectónica (ADRs)

Los documentos formales de arquitectura se encuentran disponibles en la carpeta `docs/adr/`:

### Registros de Decisiones Arquitectónicas (ADRs)
* [ADR-001: Microservicios con Bases de Datos Aisladas](docs/adr/adr_001_arquitectura_de_microservicios_con_persistencia_aislada.md)
* [ADR-002: Seguridad Perimetral y Control de Acceso por Roles con Header X-API-Key](docs/adr/adr_002_autenticaci_n_perimetral_con_header_x_api_key.md)
* [ADR-003: Comunicación Síncrona gRPC/Protobuf entre Microservicios](docs/adr/adr_003_comunicaci_n_s_ncrona_grpc_protobuf_vs_rest_interno.md) *(Con justificación de RPC Unario)*
* [ADR-004: Estrategia de Degradación Elegante y Fail-Fast](docs/adr/adr_004_estrategia_de_degradaci_n_elegante_y_fail_fast_grpc_a_http_503.md)
* [ADR-005: Estrategia de Contratos, Versionado y Evolución](docs/adr/adr-005-contrato-versionado-evolucion.md) *(Reglas de compatibilidad Protobuf y ciclo de vida de APIs)*

---

## 8. Detención del Entorno

* **Detener la ejecución preservando los datos persistidos en los volúmenes de PostgreSQL:**
  ```bash
  docker compose down
  ```

* **Restablecer el sistema borrando completamente las bases de datos:**
  ```bash
  docker compose down -v
  ```

---

## 9. Declaración de Uso de Herramientas de Inteligencia Artificial

En cumplimiento con las directrices de integridad académica y transparencia, se declara el uso asistido de modelos de lenguaje (LLM) en las siguientes actividades específicas:

* **Depuración de entorno:** Resolución de incompatibilidades en conectores de PostgreSQL y unificación de contextos de compilación en Docker Compose.
* **Documentación técnica:** Estructuración y redacción formal de los Registros de Decisiones Arquitectónicas (ADRs) bajo estándar Nygard.
* **Automatización de pruebas:** Apoyo en la estructura del script de benchmarking `medir_abet6.py` para la exportación de datos crudos y cálculo de percentiles.

*Nota:* Todo el diseño arquitectónico, lógica de negocio, batería de pruebas y análisis crítico de métricas fueron implementados, verificados y validados directamente por los autores.
