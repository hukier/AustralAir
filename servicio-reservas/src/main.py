from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.requests import Request

app = FastAPI(
    title="API Reservas - AustralAir",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

@app.get("/health")
def health_check():
    return {"status": "ok", "servicio": "reservas"}

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)