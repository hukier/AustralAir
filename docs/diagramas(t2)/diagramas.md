# Diagramas de Secuencia — AustralAir (Unidad 3)

Este documento contiene los diagramas de secuencia de los escenarios evaluados para la arquitectura orientada a eventos/Saga y resiliencia.

---

## 1. Escenario 1: Camino Feliz (Éxito Completo)

Ejecución nominal de la operación «Emitir un pasaje» coordinando Asientos, Pagos y Emisión.

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente / Gateway
    participant S as servicio-saga (Orquestador)
    participant DB as db-saga
    participant A as servicio-asientos (gRPC)
    participant P as servicio-pagos (HTTP)
    participant E as servicio-emision (HTTP)

    C->>S: POST /v1/pasajes/emitir
    activate S
    S->>DB: INSERT INTO saga_instancias (estado='INICIADA')
    
    rect rgb(240, 248, 255)
    Note over S,A: Paso 1: Reserva de Inventario
    S->>A: ReservarAsiento(vuelo_id, cantidad=1) [gRPC]
    A-->>S: ModificarCupoResponse(exito=true)
    S->>DB: UPDATE saga_instancias (estado='ASIENTO_RESERVADO')
    end

    rect rgb(240, 255, 240)
    Note over S,P: Paso 2: Cobro de Tarifa
    S->>P: POST /v1/pagos/cobrar
    P-->>S: 201 Created (pago_id)
    S->>DB: UPDATE saga_instancias (estado='PAGO_COBRADO', pago_id)
    end

    rect rgb(255, 250, 240)
    Note over S,E: Paso 3: Emisión de Boleto / PNR
    S->>E: POST /v1/boletos/emitir
    E-->>S: 201 Created (pnr, estado='EMITIDO')
    S->>DB: UPDATE saga_instancias (estado='COMPLETADA', pnr)
    end

    S-->>C: 201 Created (saga_id, pnr, estado='COMPLETADA')
    deactivate S
```

---

## 2. Escenario 2: Fallo en Último Paso y Compensación en Orden Inverso

Comportamiento ante un error 500 en `servicio-emision` (Paso 3), ejecutando compensaciones en orden inverso (Paso 2 $\rightarrow$ Paso 1).

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente / Gateway
    participant S as servicio-saga (Orquestador)
    participant DB as db-saga
    participant A as servicio-asientos (gRPC)
    participant P as servicio-pagos (HTTP)
    participant E as servicio-emision (HTTP)

    C->>S: POST /v1/pasajes/emitir
    activate S
    S->>DB: INSERT INTO saga_instancias (estado='INICIADA')

    rect rgb(240, 248, 255)
    Note over S,A: Paso 1: Reservar Asiento (Exitoso)
    S->>A: ReservarAsiento(vuelo_id, cantidad=1) [gRPC]
    A-->>S: ModificarCupoResponse(exito=true)
    S->>DB: UPDATE estado 'ASIENTO_RESERVADO'
    end

    rect rgb(240, 255, 240)
    Note over S,P: Paso 2: Cobro de Tarifa (Exitoso)
    S->>P: POST /v1/pagos/cobrar
    P-->>S: 201 Created (pago_id)
    S->>DB: UPDATE estado 'PAGO_COBRADO'
    end

    rect rgb(255, 230, 230)
    Note over S,E: Paso 3: Falla Inducida en Emisión
    S->>E: POST /v1/boletos/emitir
    E-->>S: 500 Internal Server Error (Falla IATA/GDS)
    S->>DB: UPDATE estado 'COMPENSANDO'
    end

    rect rgb(255, 240, 245)
    Note over S,A: Compensaciones en Orden Inverso (Paso 2 -> Paso 1)
    S->>P: POST /v1/pagos/reembolsar (pago_id, saga_id)
    P-->>S: 200 OK (Tarifa reembolsada)
    S->>A: LiberarAsiento(vuelo_id, cantidad=1) [gRPC]
    A-->>S: ModificarCupoResponse(exito=true)
    S->>DB: UPDATE estado 'COMPENSADA'
    end

    S-->>C: 500 Internal Server Error (Transacción compensada: cobro reembolsado y asiento liberado)
    deactivate S
```

---

## 3. Escenario 3: Resiliencia ante Dependencia Frágil (Circuit Breaker + Bulkhead)

Protección del sistema y aislamiento de hilos ante degradación o indisponibilidad en `servicio-pagos`.

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente / Red Externa
    participant GW as API Gateway
    participant BFF as BFF Web
    participant CB as Resiliencia (Circuit Breaker / Bulkhead)
    participant P as servicio-pagos (Dependencia Frágil)
    participant A as servicio-asientos (Operación Sana)

    Note over BFF,P: Flujo A: Operación sobre Dependencia Degradada
    C->>GW: POST /v1/pasajes/emitir
    GW->>BFF: Enrutar con Token validado
    BFF->>CB: Solicitar cobro en Pagos
    
    alt Límite de concurrencia alcanzado (Bulkhead)
        CB-->>BFF: BulkheadRejectedException (Rechazo inmediato)
        BFF-->>C: 429 Too Many Requests / 503 Saturación aislada
    else Errores consecutivos superan umbral
        CB->>P: POST /v1/pagos/cobrar (Retardo o Caída)
        P--xCB: Timeout (5s) o Fallo de Red
        Note over CB: Transición de estado CLOSED -> OPEN
        CB-->>BFF: CircuitBreakerOpenException (Fail-Fast + Fallback)
        BFF-->>C: 503 Service Unavailable (Respuesta en milisegundos)
    end

    Note over C,A: Flujo B: Operación Independiente (Sin contaminación)
    C->>GW: GET /v1/vuelos
    GW->>BFF: Enrutar consulta
    BFF->>A: ListarVuelos() [gRPC]
    A-->>BFF: 200 OK (Inventario disponible)
    BFF-->>C: 200 OK (Atención inmediata sin agotamiento de hilos)
```