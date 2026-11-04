"""
Microservicio: servicio-emision (AustralAir)
Genera boletos y PNRs (Passenger Name Record).
Implementa emisión atómica, anulación (compensación) e inyección de fallas.
"""

import os
import random
import string
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="AustralAir - Servicio de Emisión", version="1.0.0")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://usuario_emision:password_emision_segura@db-emision:5432/australair_emision"
)

# Flag para provocar el Escenario 2 (Fallo en último paso de la Saga)
FALLA_SIMULADA = os.environ.get("FALLA_SIMULADA_EMISION", "false").lower() == "true"


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS boletos (
                    pnr VARCHAR(10) PRIMARY KEY,
                    vuelo_id VARCHAR(50) NOT NULL,
                    pasajero_id VARCHAR(100) NOT NULL,
                    pago_id VARCHAR(100) NOT NULL,
                    estado VARCHAR(20) NOT NULL, -- 'EMITIDO', 'ANULADO'
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()


@app.on_event("startup")
def startup_event():
    init_db()


class EmitirBoletoRequest(BaseModel):
    vuelo_id: str
    pasajero_id: str
    pago_id: str
    saga_id: str


class AnularBoletoRequest(BaseModel):
    pnr: str
    saga_id: str


def generar_pnr() -> str:
    caracteres = string.ascii_uppercase + string.digits
    return "AU-" + "".join(random.choices(caracteres, k=5))


@app.get("/health")
def health():
    return {"status": "healthy", "service": "servicio-emision"}


# Endpoint de configuración dinámica de falla para la defensa en vivo
@app.post("/config/falla")
def configurar_falla(activar: bool):
    global FALLA_SIMULADA
    FALLA_SIMULADA = activar
    return {"falla_simulada_emision": FALLA_SIMULADA}


@app.post("/v1/boletos/emitir", status_code=status.HTTP_201_CREATED)
def emitir_boleto(req: EmitirBoletoRequest):
    # Simulación de falla en el paso 3 (Escenario 2 de la pauta)
    if FALLA_SIMULADA:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error simulado en Servicio de Emisión: falla de comunicación con IATA/GDS."
        )

    pnr = generar_pnr()
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Idempotencia: si ya existe boleto con ese pago_id, devolverlo
                cur.execute("SELECT * FROM boletos WHERE pago_id = %s;", (req.pago_id,))
                existente = cur.fetchone()
                if existente:
                    return existente

                cur.execute(
                    """
                    INSERT INTO boletos (pnr, vuelo_id, pasajero_id, pago_id, estado)
                    VALUES (%s, %s, %s, %s, 'EMITIDO')
                    RETURNING *;
                    """,
                    (pnr, req.vuelo_id, req.pasajero_id, req.pago_id)
                )
                boleto = cur.fetchone()
            conn.commit()
            return boleto
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos de emisión: {str(e)}"
        )


@app.post("/v1/boletos/anular")
def anular_boleto(req: AnularBoletoRequest):
    """Compensación de la Saga: anula el boleto si fue emitido."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE boletos 
                    SET estado = 'ANULADO' 
                    WHERE pnr = %s AND estado = 'EMITIDO'
                    RETURNING *;
                    """,
                    (req.pnr,)
                )
                anulado = cur.fetchone()
            conn.commit()

        if anulado:
            return {"mensaje": "Boleto anulado correctamente", "boleto": anulado}
        return {"mensaje": "Boleto ya anulado o no encontrado (idempotente)"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al anular boleto: {str(e)}"
        )