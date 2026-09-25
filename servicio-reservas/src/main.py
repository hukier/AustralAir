import uuid
from datetime import datetime, timezone
from typing import Optional, List


from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Header, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

import vuelos_pb2

from .grpc_client import cliente_asientos
from .auth import validar_api_key

from .database import get_db
from .models import Pasajero, Reserva, EstadoReservaEnum, IdempotencyRecord
from .schemas import (
    CrearPasajeroRequest,
    PasajeroResponse,
    VueloResponse,
    CrearReservaRequest,
    ReservaResponse,
    CodigoErrorEnum,
    ErrorResponse
)

app = FastAPI(
    title="API Reservas - AustralAir",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

@app.get("/health")
def health_check():
    return {"status": "ok", "servicio": "reservas"}

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if instance(exc.detail, dict) and "codigo" in exc.detail:
        # Si el detalle ya tiene un codigo de error, lo devolvemos tal cual
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={
        "codigo": CodigoErrorEnum.VALIDACION.value,
        "detalle": str(exc.detail),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

v1_router = APIRouter(prefix="/v1", dependencies=[Depends(validar_api_key)])

# Pasajeros...
@v1_router.post(
    "/pasajeros",
    response_model=PasajeroResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Pasajeros"] 
)

def crear_pasajero(data: CrearPasajeroRequest, db: Session = Depends(get_db)):
    existente = db.query(Pasajero).filter((Pasajero.rut == data.rut) | (Pasajero.email == data.email)).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_YA_EXISTE.value,
                "detalle": "Ya existe un pasajero con el mismo RUT o email.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    nuevo_pasajero = Pasajero(
        rut=data.rut,
        nombre_completo=data.nombre_completo,
        email=data.email
    )
    db.add(nuevo_pasajero)
    db.commit()
    db.refresh(nuevo_pasajero)
    return nuevo_pasajero

@v1_router.get(
    "/pasajeros",
    response_model=List[PasajeroResponse],
    tags=["Pasajeros"]
)

def listar_pasajeros(db: Session = Depends(get_db)):
    return db.query(Pasajero).all()

@v1_router.get(
    "/pasajeros/{id}",
    response_model=PasajeroResponse,
    tags=["Pasajeros"]
)

def obtener_pasajero(id: uuid.UUID, db: Session = Depends(get_db)):
    pasajero = db.query(Pasajero).filter(Pasajero.id == id).first()
    if not pasajero:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_NO_ENCONTRADO.value,
                "detalle": f"No se encontró un pasajero con ID {id}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    return pasajero

# Vuelos... (consulta federada vía gRPC)
@v1_router.get(
    "/vuelos",
    response_model=List[VueloResponse],
    tags=["Vuelos"]
)
def listar_vuelos():
    vuelos_grpc = cliente_asientos.listar_vuelos()
    return [VueloResponse(
            vuelo_id=str(v.vuelo_id),
            codigo=v.codigo,
            origen=v.origen,
            destino=v.destino,
            capacidad_total=v.capacidad_total,
            asientos_disponibles=v.asientos_disponibles
        ) 
        for v in vuelos_grpc
        ]

# Reservas...
@v1_router.post(
    "/reservas",
    response_model=ReservaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Reservas"]
)
def crear_reserva(
    data: CrearReservaRequest,
    idempotency_key: Optional[uuid.UUID] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    # Manejo de idempotencia: si se proporciona una clave de idempotencia, verificamos si ya existe un registro previo
    if idempotency_key:
        registro_existente = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == idempotency_key).first()
        if registro_existente:
            # Si ya existe un registro de idempotencia, devolvemos la respuesta almacenada
            return JSONResponse(
                status_code=registro_existente.response_code,
                content=registro_existente.response_body
            )

    # Validación de existencia del pasajero
    pasajero = db.query(Pasajero).filter(Pasajero.id == data.pasajero_id).first()
    if not pasajero:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.PASAJERO_NO_ENCONTRADO.value,
                "detalle": f"No se encontró un pasajero con ID {data.pasajero_id}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    # Validación de existencia del vuelo y disponibilidad de asientos vía gRPC
    respuesta_grpc = cliente_asientos.reservar_asiento(vuelo_id=data.vuelo_id, cantidad=1)
    
    if not respuesta_grpc.exito:
        if respuesta_grpc.codigo_error == vuelos_pb2.VUELO_NO_ENCONTRADO:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "codigo": CodigoErrorEnum.VUELO_NO_ENCONTRADO.value,
                    "detalle": f"No se encontró un vuelo con ID {data.vuelo_id}.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CodigoErrorEnum.ASIENTOS_INDISPONIBLES.value,
                "detalle": f"No hay asientos disponibles para el vuelo con ID {data.vuelo_id}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    # Creación de la reserva en la base de datos
    nueva_reserva = Reserva(
        pasajero_id=data.pasajero_id,
        vuelo_id=data.vuelo_id,
        estado=EstadoReservaEnum.CONFIRMADA
    )
    db.add(nueva_reserva)
    db.flush() # Asigna una ID y fecha en la sesion activa sin cerrar la transaccion

    payload_respuesta = {
        "id": str(nueva_reserva.id),
        "pasajero_id": str(nueva_reserva.pasajero_id),
        "vuelo_id": nueva_reserva.vuelo_id,
        "estado": nueva_reserva.estado.value,
        "creado_en": nueva_reserva.creado_en.isoformat()
    }

    # Guardamos la respuesta en la tabla de idempotencia si se proporcionó una clave
    if idempotency_key:
        registro_idempotencia = IdempotencyRecord(
            key=idempotency_key,
            response_code=status.HTTP_201_CREATED,
            response_body=payload_respuesta
        )
        db.add(registro_idempotencia)
        db.commit()

        return payload_respuesta

@v1_router.get(
    "/reservas",
    response_model=List[ReservaResponse],
    tags=["Reservas"]
)
def listar_reservas(db: Session = Depends(get_db)):
    return db.query(Reserva).all()

@v1_router.get(
    "/reservas/{id}",
    response_model=ReservaResponse,
    tags=["Reservas"]
)
def obtener_reserva(id: uuid.UUID, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == id).first()
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.RESERVA_NO_ENCONTRADA.value,
                "detalle": f"No se encontró una reserva con ID {id}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    return reserva

@v1_router.delete(
    "/reservas/{id}",
    response_model=ReservaResponse,
    tags=["Reservas"]
)
def cancelar_reserva(id: uuid.UUID, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == id).first()
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "codigo": CodigoErrorEnum.RESERVA_NO_ENCONTRADA.value,
                "detalle": f"No se encontró una reserva con ID {id}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    if reserva.estado == EstadoReservaEnum.CANCELADA:
        return reserva  # Ya está cancelada, no hacemos nada

    # Liberamos el asiento en Asientos vía gRPC
    cliente_asientos.liberar_asiento(vuelo_id=reserva.vuelo_id, cantidad=1)

    # Actualizamos el estado de la reserva a CANCELADA
    reserva.estado = EstadoReservaEnum.CANCELADA
    db.commit()
    db.refresh(reserva)

    return reserva

app.include_router(v1_router)