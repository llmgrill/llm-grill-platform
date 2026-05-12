from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.config import settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Security(_header_scheme)) -> None:
    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
