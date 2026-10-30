import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from .schemas import CodigoErrorEnum

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

METODOS_SOLO_LECTURA = {"GET", "HEAD", "OPTIONS"}


async def validar_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> str:
    """Valida X-API-Key y autoriza según rol ('operacion' permite todo; 'lectura' solo GET)."""
    operacion_key = os.getenv("API_KEY", "secreto-australair-2026")
    lectura_key = os.getenv("API_KEY_LECTURA", "lectura-australair-2026")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "codigo": CodigoErrorEnum.NO_AUTORIZADO.value,
                "detalle": "API Key no proporcionada en el header X-API-Key.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    if operacion_key and api_key == operacion_key:
        return "operacion"

    if lectura_key and api_key == lectura_key:
        if request.method in METODOS_SOLO_LECTURA:
            return "lectura"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "codigo": CodigoErrorEnum.PROHIBIDO.value,
                "detalle": "La API Key proporcionada tiene rol de solo lectura y no permite modificar recursos.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "codigo": CodigoErrorEnum.NO_AUTORIZADO.value,
            "detalle": "API Key inválida en el header X-API-Key.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )