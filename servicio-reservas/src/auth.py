import os
from datetime import datetime, timezone
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from .schemas import CodigoErrorEnum

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

EXPECTED_API_KEY = os.getenv("API_KEY")

async def validar_api_key(api_key: str = Security(api_key_header)):
    """Valida el header X-API-Key contra la variable de entorno configurada."""
    if not api_key or api_key != EXPECTED_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "codigo": CodigoErrorEnum.NO_AUTORIZADO.value,
                "detalle": "API Key inválida o no proporcionada en el header X-API-Key.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    return api_key