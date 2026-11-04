"""
Microservicio: servicio-saga (AustralAir)
Orquestador de Transacción Distribuida (Saga Pattern).
Coordina: Asientos (gRPC) -> Pagos (HTTP) -> Emisión (HTTP).
Ejecuta compensaciones en orden inverso ante fallos.
"""

import os
import sys
import uuid
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import grpc
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

# Añadir ruta de stubs gRPC
sys.path.append(os.path.join(os.path.dirname(__file__), "pb"))
import vuelos_pb2
import vuelos_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [SAGA] %(message)s")
logger = logging.getLogger("saga-orchestrator")

app = FastAPI(title="AustralAir - Orquestador Saga", version="1.0.0")

# URLs y configuraciones
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://usuario_saga:password_saga_segura@db-saga:5432/australair_saga"
)
GRPC_ASIENTOS_HOST = os.environ.get("GRPC_ASIENTOS_HOST", "servicio-asientos:50051")
PAGOS_URL = os.environ.get("PAGOS_URL", "mock")  # Si es 'mock', simula a Pagos
EMISION_URL = os.environ.get("EMISION_URL", "http://servicio-emision:8002")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS saga_instancias (
                    saga_id VARCHAR(50) PRIMARY KEY,
                    vuelo_id VARCHAR(50) NOT NULL,
                    pasajero_id VARCHAR(100) NOT NULL,
                    monto NUMERIC(10, 2) NOT NULL,
                    estado VARCHAR(30) NOT NULL,
                    pago_id VARCHAR(100),
                    pnr VARCHAR(20),
                    error_detalle TEXT,
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()


@app.on_event("startup")
def startup_event():
    init_db()


def actualizar_estado(saga_id: str, estado: str, pago_id: str = None, pnr: str = None, error: str = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE saga_instancias
                SET estado = %s,
                    pago_id = COALESCE(%s, pago_id),
                    pnr = COALESCE(%s, pnr),
                    error_detalle = COALESCE(%s, error_detalle),
                    actualizado_en = CURRENT_TIMESTAMP
                WHERE saga_id = %s;
            """, (estado, pago_id, pnr, error, saga_id))
        conn.commit()


class EmitirPasajeRequest(BaseModel):
    vuelo_id: str
    pasajero_id: str
    monto: float = 45000.0


@app.get("/health")
def health():
    return {"status": "healthy", "service": "servicio-saga"}


@app.get("/v1/sagas/{saga_id}")
def obtener_saga(saga_id: str):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM saga_instancias WHERE saga_id = %s;", (saga_id,))
            res = cur.fetchone()
    if not res:
        raise HTTPException(status_code=404, detail="Saga no encontrada")
    return res


# --------------------------------------------------------------------------
# LLAMADAS A PASOS Y COMPENSACIONES
# --------------------------------------------------------------------------

def paso1_reservar_asiento(vuelo_id: str) -> bool:
    """Paso 1: Reserva cupo en servicio-asientos vía gRPC."""
    logger.info(f"Ejecutando Paso 1: Reservar cupo en vuelo {vuelo_id} (gRPC)")
    try:
        with grpc.insecure_channel(GRPC_ASIENTOS_HOST) as channel:
            stub = vuelos_pb2_grpc.AsientosServiceStub(channel)
            req = vuelos_pb2.ModificarCupoRequest(vuelo_id=vuelo_id, cantidad=1)
            resp = stub.ReservarAsiento(req, timeout=3.0)
            return resp.exito
    except Exception as e:
        logger.error(f"Falla en Paso 1 (Asientos gRPC): {e}")
        return False


def compensar1_liberar_asiento(vuelo_id: str):
    """Compensación 1: Devuelve el asiento reservado."""
    logger.warning(f"COMPENSANDO Paso 1: Liberando asiento en vuelo {vuelo_id} (gRPC)")
    try:
        with grpc.insecure_channel(GRPC_ASIENTOS_HOST) as channel:
            stub = vuelos_pb2_grpc.AsientosServiceStub(channel)
            req = vuelos_pb2.ModificarCupoRequest(vuelo_id=vuelo_id, cantidad=1)
            stub.LiberarAsiento(req, timeout=3.0)
    except Exception as e:
        logger.critical(f"Error crítico compensando Paso 1: {e}")


def paso2_cobrar_tarifa(saga_id: str, pasajero_id: str, monto: float) -> str:
    """Paso 2: Realiza el cobro en servicio-pagos."""
    logger.info(f"Ejecutando Paso 2: Cobrar tarifa ${monto} a {pasajero_id}")
    if PAGOS_URL == "mock":
        return f"MOCK-PAY-{uuid.uuid4().hex[:8]}"

    payload = {"saga_id": saga_id, "pasajero_id": pasajero_id, "monto": monto}
    resp = requests.post(f"{PAGOS_URL}/v1/pagos/cobrar", json=payload, timeout=5.0)
    if resp.status_code == 200 or resp.status_code == 201:
        return resp.json().get("pago_id")
    raise Exception(f"Cobro rechazado: {resp.text}")


def compensar2_reembolsar(pago_id: str, saga_id: str):
    """Compensación 2: Reembolsa el cobro efectuado."""
    logger.warning(f"COMPENSANDO Paso 2: Reembolsando cobro {pago_id}")
    if PAGOS_URL == "mock":
        return
    try:
        payload = {"pago_id": pago_id, "saga_id": saga_id}
        requests.post(f"{PAGOS_URL}/v1/pagos/reembolsar", json=payload, timeout=5.0)
    except Exception as e:
        logger.critical(f"Error crítico compensando Paso 2: {e}")


def paso3_emitir_boleto(vuelo_id: str, pasajero_id: str, pago_id: str, saga_id: str) -> str:
    """Paso 3: Emite boleto y PNR en servicio-emision."""
    logger.info(f"Ejecutando Paso 3: Emitir boleto para {pasajero_id}")
    payload = {
        "vuelo_id": vuelo_id,
        "pasajero_id": pasajero_id,
        "pago_id": pago_id,
        "saga_id": saga_id
    }
    resp = requests.post(f"{EMISION_URL}/v1/boletos/emitir", json=payload, timeout=5.0)
    if resp.status_code == 201:
        return resp.json().get("pnr")
    raise Exception(f"Emisión falló: {resp.text}")


def compensar3_anular_boleto(pnr: str, saga_id: str):
    """Compensación 3: Anula el boleto emitido."""
    logger.warning(f"COMPENSANDO Paso 3: Anulando boleto PNR {pnr}")
    try:
        payload = {"pnr": pnr, "saga_id": saga_id}
        requests.post(f"{EMISION_URL}/v1/boletos/anular", json=payload, timeout=5.0)
    except Exception as e:
        logger.critical(f"Error crítico compensando Paso 3: {e}")


# --------------------------------------------------------------------------
# OPERACIÓN CENTRAL DE LA SAGA
# --------------------------------------------------------------------------

@app.post("/v1/pasajes/emitir", status_code=status.HTTP_201_CREATED)
def emitir_pasaje(req: EmitirPasajeRequest):
    saga_id = f"SAGA-{uuid.uuid4().hex[:10]}"
    logger.info(f"=== INICIANDO SAGA {saga_id} ===")

    # Registrar inicio
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO saga_instancias (saga_id, vuelo_id, pasajero_id, monto, estado)
                VALUES (%s, %s, %s, %s, 'INICIADA');
            """, (saga_id, req.vuelo_id, req.pasajero_id, req.monto))
        conn.commit()

    asiento_ok = False
    pago_id = None
    pnr = None

    try:
        # PASO 1: Reservar Asiento
        asiento_ok = paso1_reservar_asiento(req.vuelo_id)
        if not asiento_ok:
            actualizar_estado(saga_id, "FALLIDA", error="Sin cupo o falla en Asientos")
            raise HTTPException(status_code=409, detail="No fue posible reservar asiento (sin cupo o servicio caído)")
        actualizar_estado(saga_id, "ASIENTO_RESERVADO")

        # PASO 2: Cobrar Tarifa
        try:
            pago_id = paso2_cobrar_tarifa(saga_id, req.pasajero_id, req.monto)
            actualizar_estado(saga_id, "PAGO_COBRADO", pago_id=pago_id)
        except Exception as e:
            logger.error(f"Paso 2 falló: {e}. Iniciando compensaciones...")
            actualizar_estado(saga_id, "COMPENSANDO", error=str(e))
            compensar1_liberar_asiento(req.vuelo_id)
            actualizar_estado(saga_id, "COMPENSADA")
            raise HTTPException(status_code=502, detail=f"Fallo en cobro: {str(e)}. Asiento liberado.")

        # PASO 3: Emitir Boleto
        try:
            pnr = paso3_emitir_boleto(req.vuelo_id, req.pasajero_id, pago_id, saga_id)
            actualizar_estado(saga_id, "COMPLETADA", pnr=pnr)
        except Exception as e:
            # Fallo del último paso (Escenario 2 de la defensa)
            logger.error(f"Paso 3 falló: {e}. Iniciando compensaciones en orden inverso...")
            actualizar_estado(saga_id, "COMPENSANDO", error=str(e))
            
            # Orden inverso de compensación: Paso 2 -> Paso 1
            compensar2_reembolsar(pago_id, saga_id)
            compensar1_liberar_asiento(req.vuelo_id)
            
            actualizar_estado(saga_id, "COMPENSADA")
            raise HTTPException(
                status_code=500,
                detail=f"Fallo al emitir boleto: {str(e)}. Transacción compensada (reembolso realizado y asiento liberado)."
            )

        logger.info(f"=== SAGA {saga_id} COMPLETADA CON ÉXITO (PNR: {pnr}) ===")
        return {
            "saga_id": saga_id,
            "estado": "COMPLETADA",
            "vuelo_id": req.vuelo_id,
            "pasajero_id": req.pasajero_id,
            "pago_id": pago_id,
            "pnr": pnr,
            "mensaje": "Pasaje emitido exitosamente tras transacción distribuida consistente."
        }

    except HTTPException:
        raise
    except Exception as e:
        actualizar_estado(saga_id, "FALLIDA", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error inesperado en Saga: {str(e)}")