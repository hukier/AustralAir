from fastapi import FastAPI

app = FastAPI(
    title="API Reservas - AustralAir",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

@app.get("/health")
def health_check():
    return {"status": "ok", "servicio": "reservas"}