import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field

class CodigoErrorEnum(str, Enum):
    PASAJERO_NO_ENCONTRADO = "PASAJERO_NO_ENCONTRADO"
    VUELO_NO_ENCONTRADO = "VUELO_NO_ENCONTRADO"
    ASIENTOS_INDISPONIBLES = "ASIENTOS_INDISPONIBLES"
    SERVICIO_NO_DISPONIBLE = "SERVICIO_NO_DISPONIBLE"
    VALIDACION = "VALIDACION"
    NO_AUTORIZADO = "NO_AUTORIZADO"
    ERROR_INTERNO = "ERROR_INTERNO"

class ErrorResponse(BaseModel):
    codigo: CodigoErrorEnum
    detalle: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# --- Esquemas de Pasajeros ---
class CrearPasajeroRequest(BaseModel):
    rut: str = Field(..., examples=["18945632-1"])
    nombre_completo: str = Field(..., examples=["Camila Soto"])
    email: EmailStr = Field(..., examples=["camila.soto@email.com"])

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
    vuelo_id: str

class ReservaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pasajero_id: uuid.UUID
    vuelo_id: str
    estado: EstadoReservaEnum
    creado_en: datetime