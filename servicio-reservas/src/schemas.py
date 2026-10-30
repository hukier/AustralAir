import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator

class EstadoReservaEnum(str, Enum):
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"

class CodigoErrorEnum(str, Enum):
    PASAJERO_NO_ENCONTRADO = "PASAJERO_NO_ENCONTRADO"
    PASAJERO_YA_EXISTE = "PASAJERO_YA_EXISTE"
    RESERVA_NO_ENCONTRADA = "RESERVA_NO_ENCONTRADA"
    VUELO_NO_ENCONTRADO = "VUELO_NO_ENCONTRADO"
    ASIENTOS_INDISPONIBLES = "ASIENTOS_INDISPONIBLES"
    SERVICIO_NO_DISPONIBLE = "SERVICIO_NO_DISPONIBLE"
    VALIDACION = "VALIDACION"
    NO_AUTORIZADO = "NO_AUTORIZADO"
    PROHIBIDO = "PROHIBIDO"
    CONFLICTO_IDEMPOTENCIA = "CONFLICTO_IDEMPOTENCIA"
    ERROR_INTERNO = "ERROR_INTERNO"

class ErrorResponse(BaseModel):
    codigo: CodigoErrorEnum
    detalle: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# --- Esquemas de Pasajeros ---
class CrearPasajeroRequest(BaseModel):
    rut: str = Field(..., pattern=r"^\d{7,8}-[\dkK]$", examples=["18945632-1"])
    nombre_completo: str = Field(..., min_length=2, max_length=150, examples=["Camila Soto"])
    email: EmailStr = Field(..., max_length=150, examples=["camila.soto@email.com"])

    @field_validator("rut")
    @classmethod
    def normalizar_rut(cls, v: str) -> str:
        return v[:-1] + v[-1].upper()

    @field_validator("nombre_completo")
    @classmethod
    def validar_nombre_no_vacio(cls, v: str) -> str:
        limpio = v.strip()
        if len(limpio) < 2:
            raise ValueError("El nombre completo debe contener al menos 2 caracteres válidos.")
        return limpio

class PasajeroResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rut: str
    nombre_completo: str
    email: str

# --- Esquemas de Vuelos (Lectura federada gRPC) ---
class VueloResponse(BaseModel):
    vuelo_id: str
    codigo: str
    origen: str
    destino: str
    capacidad_total: int
    asientos_disponibles: int

# --- Esquemas de Reservas ---
class CrearReservaRequest(BaseModel):
    pasajero_id: uuid.UUID
    vuelo_id: str = Field(..., min_length=1, max_length=50)

class ReservaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pasajero_id: uuid.UUID
    vuelo_id: str
    estado: EstadoReservaEnum
    creado_en: datetime