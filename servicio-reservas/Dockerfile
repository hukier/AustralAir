FROM python:3.11-slim

WORKDIR /app

# Copiar dependencias e instalarlas
COPY servicio-reservas/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del servicio
COPY servicio-reservas/ .

# Copiar la ÚNICA fuente de verdad del proto desde la raíz
COPY proto/ ./proto/

# Generar stubs gRPC en /app/pb
RUN mkdir -p /app/pb && \
    python -m grpc_tools.protoc -I./proto --python_out=/app/pb --grpc_python_out=/app/pb ./proto/vuelos.proto

ENV PYTHONPATH="/app:/app/pb:${PYTHONPATH}"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]