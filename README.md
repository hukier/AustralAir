# AustralAir - Sistema Distribuido de Reservas e Inventario de Vuelos

Plataforma de reservas de vuelos e inventario atómico de asientos construida sobre una arquitectura de microservicios orientada a resiliencia, persistencia aislada (*Database-per-Service*) y comunicación interna de alto rendimiento mediante gRPC.

---

## 1. Arquitectura General del Sistema

El sistema implementa dos microservicios autónomos desplegados en contenedores Docker y segmentados en redes virtuales aisladas:

* **`servicio-reservas` (API Gateway / Perímetro):**
  * Expone API REST pública en el puerto `8000` bajo el prefijo versionado `/v1`.
  * Autenticación perimetral obligatoria mediante cabecera HTTP `X-API-Key: secreto-australair-2026`.
  * Base de datos relacional independiente: `db-reservas` (PostgreSQL en puerto interno `5432`). Gestiona tablas `pasajeros` y `reservas`.
  * Actúa como cliente gRPC consumiendo las capacidades del catálogo de asientos.
  * Implementa patrón **Fail-Fast** con timeout de 3.0 segundos y degradación controlada retornando `HTTP 503 Service Unavailable` estructurado.
  * Documentación interactiva Swagger/OpenAPI disponible en `http://localhost:8000/docs`.

* **`servicio-asientos` (Backend de Inventario):**
  * Expone servicios RPC vía **gRPC / Protocol Buffers** en el puerto `50051`.
  * Base de datos relacional independiente: `db-asientos` (PostgreSQL en puerto interno `5432`). Gestiona tablas `vuelos` y `asientos`.
  * Garantiza transaccionalidad atómica y previene sobreventas con lógica SQL condicional (`WHERE asientos_disponibles >= $cantidad`).
  * Lógica de liberación acotada al límite físico de la aeronave mediante función SQL `LEAST()`.

---

## 2. Prerrequisitos y Configuración

* **Docker** y **Docker Compose v2** o superior en ejecución.
* **Python 3.10+** instalado en el host para ejecutar los scripts de prueba y benchmarking.
* Paquetes Python locales necesarios para la medición:
  ```bash
  pip install requests numpy
  ```

### Configuración de Variables de Entorno y Secretos (`.env`)

El despliegue aplica validación estricta de variables en `docker-compose.yml` mediante el patrón `${VAR:?msg}`. Cree un archivo llamado `.env` en la raíz del proyecto (`/AustralAir/.env`):

```dotenv
API_KEY=secreto-australair-2026

POSTGRES_USER_RESERVAS=usuario_reservas
POSTGRES_PASSWORD_RESERVAS=password_reservas_segura
POSTGRES_DB_RESERVAS=australair_reservas

POSTGRES_USER_ASIENTOS=usuario_asientos
POSTGRES_PASSWORD_ASIENTOS=password_asientos_segura
POSTGRES_DB_ASIENTOS=australair_asientos
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

   Deben figurar en estado activo (`Up`) y con salud óptima (`healthy`):
   * `australair-reservas`
   * `australair-asientos`
   * `australair-db-reservas` (`healthy`)
   * `australair-db-asientos` (`healthy`)

---

## 4. Endpoints de la API REST (`servicio-reservas`)

La documentación OpenAPI interactiva se encuentra habilitada en `http://localhost:8000/docs`. Todas las rutas bajo `/v1` requieren el encabezado de autenticación perimetral:

```http
X-API-Key: secreto-australair-2026
```

### Tabla de Rutas Principales:

| Método | Endpoint | Descripción | Parámetros / Payload Requerido |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Verificación de estado del gateway (público) | N/A |
| `POST` | `/v1/pasajeros` | Registra un nuevo pasajero | `{"rut": "18945632-1", "nombre_completo": "...", "email": "..."}` |
| `GET` | `/v1/vuelos` | Consulta catálogo de vuelos vía gRPC | N/A |
| `POST` | `/v1/reservas` | Crea y confirma una reserva | `{"pasajero_id": "UUID", "vuelo_id": "1"}` |
| `GET` | `/v1/reservas/{id}` | Consulta el estado de una reserva | Parámetro `id` (UUID) en URL |

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

Para comprobar los 8 casos transaccionales (rutas exitosas, prevención de sobreventa, vuelos inexistentes y tope de capacidad vía `LEAST`), ejecute:

```bash
docker compose exec servicio-asientos python test_client.py
```

---

## 6. Experimento de Ingeniería ABET 6: Evaluación Bajo Degradación

El experimento evalúa el comportamiento del sistema ante latencia sintética inyectada en la llamada gRPC `ListarVuelos`, midiendo Throughput (req/s), percentiles de latencia ($p50, p95, p99$) y tasa de fallos HTTP (200 OK vs 503 Service Unavailable) bajo 100 peticiones concurrentes ($C=10$).

### Protocolo de Ejecución de los 4 Escenarios:

#### En entornos Linux / WSL / macOS:

```bash
# Escenario 1: Base (0.0s de retardo)
LATENCIA_SIMULADA=0.0 docker compose up -d servicio-asientos && python3 medir_abet6.py "Escenario 1: Base"

# Escenario 2: Degradación Moderada (0.5s de retardo)
LATENCIA_SIMULADA=0.5 docker compose up -d servicio-asientos && python3 medir_abet6.py "Escenario 2: 500ms"

# Escenario 3: Límite Operacional (2.5s de retardo)
LATENCIA_SIMULADA=2.5 docker compose up -d servicio-asientos && python3 medir_abet6.py "Escenario 3: 2500ms"

# Escenario 4: Superación de Timeout / Fail-Fast (4.0s de retardo)
LATENCIA_SIMULADA=4.0 docker compose up -d servicio-asientos && python3 medir_abet6.py "Escenario 4: Fail-Fast 4000ms"
```

#### En PowerShell (Windows):

```powershell
# Escenario 1: Base (0.0s de retardo)
$env:LATENCIA_SIMULADA="0.0"; docker compose up -d --force-recreate servicio-asientos; python medir_abet6.py

# Escenario 2: Degradación Moderada (0.5s de retardo)
$env:LATENCIA_SIMULADA="0.5"; docker compose up -d --force-recreate servicio-asientos; python medir_abet6.py

# Escenario 3: Límite Operacional (2.5s de retardo)
$env:LATENCIA_SIMULADA="2.5"; docker compose up -d --force-recreate servicio-asientos; python medir_abet6.py

# Escenario 4: Superación de Timeout / Fail-Fast (4.0s de retardo)
$env:LATENCIA_SIMULADA="4.0"; docker compose up -d --force-recreate servicio-asientos; python medir_abet6.py
```

### Resultados Empíricos Registrados:

| Escenario | Retardo Inyectado | Throughput | Latencia $p50$ | Latencia $p95$ | Latencia $p99$ | Distribución HTTP |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Base** | 0.0 s | 85.25 req/s | 81.45 ms | 277.31 ms | 392.34 ms | 100% 200 OK |
| **2. Moderado** | 0.5 s | 16.47 req/s | 535.10 ms | 1196.02 ms | 1211.36 ms | 100% 200 OK |
| **3. Límite** | 2.5 s | 3.89 req/s | 2527.77 ms | 2931.71 ms | 2944.59 ms | 100% 200 OK |
| **4. Fail-Fast** | 4.0 s | 3.28 req/s | 3018.21 ms | 3208.98 ms | 3306.91 ms | 100% 503 Unavailable |

> **Conclusión técnica:** Al superar el límite de tolerancia de 3.0 s en el Escenario 4, el cliente gRPC corta la ejecución exactamente a los $\approx 3.01\,\text{s}$ ($p50$) retornando HTTP 503, liberando los hilos del API Gateway e impidiendo el bloqueo acumulativo de la plataforma.

---

## 7. Registros de Decisión Arquitectónica (ADRs)

Los documentos formales de arquitectura se encuentran disponibles en la carpeta `docs/adr/`:

* [ADR-001: Adopción de Arquitectura de Microservicios con Bases de Datos Aisladas](docs/adr/ADR-001-microservicios-bases-datos-aisladas.md)
* [ADR-002: Seguridad Perimetral Mediante Autenticación Estática con Header X-API-Key](docs/adr/ADR-002-seguridad-perimetral-api-key.md)
* [ADR-003: Comunicación Síncrona gRPC/Protobuf entre Microservicios](docs/adr/ADR-003-comunicacion-grpc-protobuf.md)
* [ADR-004: Estrategia de Degradación Elegante y Mapeo de Excepciones gRPC a HTTP 503](docs/adr/ADR-004-degradacion-elegante-timeout-503.md)

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
