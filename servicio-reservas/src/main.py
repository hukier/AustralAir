import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Header, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

import vuelos_pb2

from .grpc_client import cliente_asientos
from .auth import validar_api_key
from .database import Base, engine, get_db
from .models import Pasajero, Reserva, EstadoReservaEnum, IdempotencyRecord
from .schemas import (
    CrearPasajeroRequest,
    PasajeroResponse,
    VueloResponse,
    CrearReservaRequest,
    ReservaResponse,
    CodigoErrorEnum,
    ErrorResponse,
)

logger = logging.getLogger("australair.reservas")


def inicializar_esquema_bd() -> None:
    """Garantiza idempotentemente que existan tipos, tablas y columnas en db-reservas."""
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(
                text(
                    """
                    DO $$ BEGIN
                        CREATE TYPE estado_reserva AS ENUM ('CONFIRMADA', 'CANCELADA');
                    EXCEPTION
                        WHEN duplicate_object THEN NULL;
                    END $$;
                    """
                )
            )
        Base.metadata.create_all(bind=conn)
        if conn.dialect.name == "postgresql":
            conn.execute(
                text(
                    "ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64) NOT NULL DEFAULT '';"
                )
            )
            conn.execute(
                text("ALTER TABLE idempotency_keys ALTER COLUMN response_code DROP NOT NULL;")
            )
            conn.execute(
                text("ALTER TABLE idempotency_keys ALTER COLUMN response_body DROP NOT NULL;")
            )
            conn.execute(
                text(
                    """
                    INSERT INTO pasajeros (id, rut, nombre_completo, email)
                    VALUES ('e4eebc99-9c0b-4ef8-bb6d-6bb9bd380a55', '19876543-2', 'Camila Soto', 'camila.soto@email.com')
                    ON CONFLICT (rut) DO NOTHING;
                    """
                )
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        inicializar_esquema_bd()
    except Exception as exc:
        logger.warning("No se pudo verificar el esquema inicial de base de datos: %s", exc)
    yield


app = FastAPI(
    title="API Reservas - AustralAir",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    return {"status": "ok", "servicio": "reservas"}


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "codigo" in exc.detail:
        # Preservar cabeceras como Retry-After en respuestas 503
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )

    mapa_codigos = {
        status.HTTP_401_UNAUTHORIZED: CodigoErrorEnum.NO_AUTORIZADO.value,
        status.HTTP_403_FORBIDDEN: CodigoErrorEnum.PROHIBIDO.value,
        status.HTTP_409_CONFLICT: CodigoErrorEnum.CONFLICTO_IDEMPOTENCIA.value,
        status.HTTP_503_SERVICE_UNAVAILABLE: CodigoErrorEnum.SERVICIO_NO_DISPONIBLE.value,
    }
    codigo = mapa_codigos.get(
        exc.status_code,
        CodigoErrorEnum.ERROR_INTERNO.value
        if exc.status_code >= 500
        else CodigoErrorEnum.VALIDACION.value,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "codigo": codigo,
            "detalle": str(exc.detail),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errores = exc.errors()
    es_json_invalido = any(err.get("type") == "json_invalid" for err in errores)

    if es_json_invalido:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "codigo": CodigoErrorEnum.VALIDACION.value,
                "detalle": "El cuerpo de la solicitud no contiene un JSON válido.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    detalles = []
    for err in errores:
        ubicacion = ".".join(str(loc) for loc in err.get("loc", []))
        mensaje = err.get("msg", "Valor inválido")
        detalles.append(f"{ubicacion}: {mensaje}" if ubicacion else mensaje)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "codigo": CodigoErrorEnum.VALIDACION.value,
            "detalle": f"Error de validación en la entrada: {'; '.join(detalles)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Excepción no controlada procesando %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "codigo": CodigoErrorEnum.ERROR_INTERNO.value,
            "detalle": "Ocurrió un error interno inesperado en el servicio de reservas.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


v1_router = APIRouter(prefix="/v1", dependencies=[Depends(validar_api_key)])


# Pasajeros...
@v1_router.post(
    "/pasajeros",
    response_model=PasajeroResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Pasajeros"],
)
def crear_pasajero(data: CrearPasajeroRequest, db: Session = Depends(get_db)):
    existente = (
        db.query(Pasajero)
        .filter((Pasajero.rut == data.rut) | (Pasajero.email == data.email))
        .first()
    )
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_YA_EXISTE.value,
                "detalle": "Ya existe un pasajero con el mismo RUT o email.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    nuevo_pasajero = Pasajero(
        rut=data.rut,
        nombre_completo=data.nombre_completo,
        email=data.email,
    )
    db.add(nuevo_pasajero)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_YA_EXISTE.value,
                "detalle": "Ya existe un pasajero con el mismo RUT o email.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ) from exc

    db.refresh(nuevo_pasajero)
    return nuevo_pasajero


@v1_router.get(
    "/pasajeros",
    response_model=List[PasajeroResponse],
    tags=["Pasajeros"],
)
def listar_pasajeros(db: Session = Depends(get_db)):
    return db.query(Pasajero).all()


@v1_router.get(
    "/pasajeros/{id}",
    response_model=PasajeroResponse,
    tags=["Pasajeros"],
)
def obtener_pasajero(id: uuid.UUID, db: Session = Depends(get_db)):
    pasajero = db.query(Pasajero).filter(Pasajero.id == id).first()
    if not pasajero:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_NO_ENCONTRADO.value,
                "detalle": f"No se encontró un pasajero con ID {id}.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    return pasajero


# Vuelos... (consulta federada vía gRPC)
@v1_router.get(
    "/vuelos",
    response_model=List[VueloResponse],
    tags=["Vuelos"],
)
def listar_vuelos():
    vuelos_grpc = cliente_asientos.listar_vuelos()
    return [
        VueloResponse(
            vuelo_id=str(v.vuelo_id),
            codigo=v.codigo,
            origen=v.origen,
            destino=v.destino,
            capacidad_total=v.capacidad_total,
            asientos_disponibles=v.asientos_disponibles,
        )
        for v in vuelos_grpc
    ]


# Reservas...
@v1_router.post(
    "/reservas",
    response_model=ReservaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Reservas"],
)
def crear_reserva(
    data: CrearReservaRequest,
    idempotency_key: Optional[uuid.UUID] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    # 1. Blindaje de idempotencia concurrente: reservar la clave en BD ANTES de llamar a gRPC
    if idempotency_key:
        canonical_payload = json.dumps(
            {"pasajero_id": str(data.pasajero_id), "vuelo_id": data.vuelo_id},
            sort_keys=True,
        )
        request_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        key_str = str(idempotency_key)

        insertado = db.execute(
            text(
                """
                INSERT INTO idempotency_keys (key, request_hash, response_code, response_body)
                VALUES (CAST(:key AS uuid), :request_hash, NULL, NULL)
                ON CONFLICT (key) DO NOTHING
                RETURNING key
                """
            ),
            {"key": key_str, "request_hash": request_hash},
        ).fetchone()

        if insertado is None:
            existente = db.execute(
                text(
                    """
                    SELECT request_hash, response_code, response_body
                    FROM idempotency_keys
                    WHERE key = CAST(:key AS uuid)
                    """
                ),
                {"key": key_str},
            ).fetchone()
            db.rollback()

            if existente is None or existente.response_body is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "codigo": CodigoErrorEnum.CONFLICTO_IDEMPOTENCIA.value,
                        "detalle": "Ya existe una solicitud en procesamiento para esta Idempotency-Key.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            if existente.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "codigo": CodigoErrorEnum.CONFLICTO_IDEMPOTENCIA.value,
                        "detalle": "La cabecera Idempotency-Key ya fue utilizada con parámetros distintos.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            cuerpo_guardado = (
                json.loads(existente.response_body)
                if isinstance(existente.response_body, str)
                else existente.response_body
            )
            return JSONResponse(
                status_code=existente.response_code or status.HTTP_201_CREATED,
                content=cuerpo_guardado,
            )

    # 2. Validación de existencia del pasajero
    pasajero = db.query(Pasajero).filter(Pasajero.id == data.pasajero_id).first()
    if not pasajero:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_NO_ENCONTRADO.value,
                "detalle": f"No se encontró un pasajero con ID {data.pasajero_id}.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # 3. Validación de existencia del vuelo y descuento atómico de asiento vía gRPC
    try:
        respuesta_grpc = cliente_asientos.reservar_asiento(vuelo_id=data.vuelo_id, cantidad=1)
    except Exception:
        db.rollback()
        raise

    if not respuesta_grpc.exito:
        db.rollback()
        if respuesta_grpc.codigo_error == vuelos_pb2.VUELO_NO_ENCONTRADO:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "codigo": CodigoErrorEnum.VUELO_NO_ENCONTRADO.value,
                    "detalle": f"No se encontró un vuelo con ID {data.vuelo_id}.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.ASIENTOS_INDISPONIBLES.value,
                "detalle": f"No hay asientos disponibles para el vuelo con ID {data.vuelo_id}.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # 4. Guardado local con compensación automática ante fallos en db-reservas
    try:
        nueva_reserva = Reserva(
            pasajero_id=data.pasajero_id,
            vuelo_id=data.vuelo_id,
            estado=EstadoReservaEnum.CONFIRMADA,
        )
        db.add(nueva_reserva)
        db.flush()  # Asigna ID y creado_en en la sesión activa

        payload_respuesta = {
            "id": str(nueva_reserva.id),
            "pasajero_id": str(nueva_reserva.pasajero_id),
            "vuelo_id": nueva_reserva.vuelo_id,
            "estado": nueva_reserva.estado.value,
            "creado_en": nueva_reserva.creado_en.isoformat(),
        }

        if idempotency_key:
            db.execute(
                text(
                    """
                    UPDATE idempotency_keys
                    SET response_code = :code,
                        response_body = CAST(:body AS jsonb)
                    WHERE key = CAST(:key AS uuid)
                    """
                ),
                {
                    "code": status.HTTP_201_CREATED,
                    "body": json.dumps(payload_respuesta),
                    "key": str(idempotency_key),
                },
            )

        db.commit()
        return payload_respuesta
    except Exception as exc:
        db.rollback()
        try:
            cliente_asientos.liberar_asiento(vuelo_id=data.vuelo_id, cantidad=1)
        except Exception as comp_exc:
            logger.error(
                "Fallo crítico al compensar asiento del vuelo %s tras error en BD local: %s",
                data.vuelo_id,
                comp_exc,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "codigo": CodigoErrorEnum.ERROR_INTERNO.value,
                "detalle": "Falló el registro local de la reserva; el cupo de asiento fue compensado.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ) from exc


@v1_router.get(
    "/reservas",
    response_model=List[ReservaResponse],
    tags=["Reservas"],
)
def listar_reservas(db: Session = Depends(get_db)):
    return db.query(Reserva).all()


@v1_router.get(
    "/reservas/{id}",
    response_model=ReservaResponse,
    tags=["Reservas"],
)
def obtener_reserva(id: uuid.UUID, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == id).first()
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.RESERVA_NO_ENCONTRADA.value,
                "detalle": f"No se encontró una reserva con ID {id}.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    return reserva


@v1_router.delete(
    "/reservas/{id}",
    response_model=ReservaResponse,
    tags=["Reservas"],
)
def cancelar_reserva(id: uuid.UUID, db: Session = Depends(get_db)):
    # 1. UPDATE condicional atómico: evita condiciones de carrera y múltiples liberaciones
    fila_actualizada = db.execute(
        text(
            """
            UPDATE reservas
            SET estado = 'CANCELADA'
            WHERE id = CAST(:id AS uuid) AND estado = 'CONFIRMADA'
            RETURNING id, pasajero_id, vuelo_id, estado, creado_en
            """
        ),
        {"id": str(id)},
    ).fetchone()

    if fila_actualizada is None:
        reserva = db.query(Reserva).filter(Reserva.id == id).first()
        if not reserva:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "codigo": CodigoErrorEnum.RESERVA_NO_ENCONTRADA.value,
                    "detalle": f"No se encontró una reserva con ID {id}.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        # Ya estaba CANCELADA: respuesta idempotente 200 OK sin volver a llamar a gRPC
        return reserva

    # 2. Liberar el asiento en Asientos vía gRPC solo para la transición efectiva CONFIRMADA -> CANCELADA
    try:
        respuesta_grpc = cliente_asientos.liberar_asiento(
            vuelo_id=fila_actualizada.vuelo_id,
            cantidad=1,
        )
    except Exception:
        db.rollback()
        raise

    if not respuesta_grpc.exito:
        db.rollback()
        if respuesta_grpc.codigo_error == vuelos_pb2.VUELO_NO_ENCONTRADO:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "codigo": CodigoErrorEnum.VUELO_NO_ENCONTRADO.value,
                    "detalle": f"No se encontró el vuelo con ID {fila_actualizada.vuelo_id}.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.ERROR_INTERNO.value,
                "detalle": f"No se pudo restituir el cupo en el servicio de Asientos: {respuesta_grpc.mensaje}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # 3. Confirmar la cancelación; si falla el commit local tras liberar cupo, compensar re-reservando
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            cliente_asientos.reservar_asiento(vuelo_id=fila_actualizada.vuelo_id, cantidad=1)
        except Exception as comp_exc:
            logger.error(
                "Fallo crítico al revertir liberación del vuelo %s tras error en commit local: %s",
                fila_actualizada.vuelo_id,
                comp_exc,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "codigo": CodigoErrorEnum.ERROR_INTERNO.value,
                "detalle": "Error al confirmar la cancelación en la base de datos local.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ) from exc

    return {
        "id": fila_actualizada.id,
        "pasajero_id": fila_actualizada.pasajero_id,
        "vuelo_id": fila_actualizada.vuelo_id,
        "estado": EstadoReservaEnum.CANCELADA,
        "creado_en": fila_actualizada.creado_en,
    }


app.include_router(v1_router)
