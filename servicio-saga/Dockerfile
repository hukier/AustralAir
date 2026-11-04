FROM python:3.11-slim

WORKDIR /app

COPY servicio-saga/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servicio-saga/src/ ./src/
COPY proto/ ./proto/

# Compilar stubs gRPC en /app/src/pb
RUN mkdir -p /app/src/pb && \
    python -m grpc_tools.protoc -I./proto --python_out=/app/src/pb --grpc_python_out=/app/src/pb ./proto/vuelos.proto

ENV PYTHONPATH="/app:/app/src/pb"

EXPOSE 8003

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003"]