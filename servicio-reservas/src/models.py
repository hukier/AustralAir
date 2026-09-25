import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

class EstadoReservaEnum(str, enum.Enum):
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"

class Pasajero(Base):
    __tablename__ = "pasajeros"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rut: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)
    nombre_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reservas: Mapped[list["Reserva"]] = relationship("Reserva", back_populates="pasajero")

class Reserva(Base):
    __tablename__ = "reservas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pasajero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pasajeros.id", ondelete="RESTRICT"), nullable=False)
    # Referencia logica a Asientos
    vuelo_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # sin Foreign Key fisica para respetar T5
    estado: Mapped[EstadoReservaEnum] = mapped_column(
        SQLEnum(EstadoReservaEnum, name="estado_reserva", create_type=False),
        default=EstadoReservaEnum.CONFIRMADA,
        nullable=False
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pasajero: Mapped["Pasajero"] = relationship("Pasajero", back_populates="reservas")

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())