FROM python:3.11-slim

WORKDIR /app

# Instalación de dependencias de runtime y compilador gRPC
RUN pip install --no-cache-dir grpcio==1.59.0 grpcio-tools==1.59.0 psycopg2-binary==2.9.9

# Copiar el código del servicio
COPY servicio-asientos/ .

# Copiar la ÚNICA fuente de verdad del contrato gRPC desde la raíz
COPY proto/ ./proto/

# Crear carpeta de stubs y compilar el archivo proto
RUN mkdir -p /app/pb && \
    python -m grpc_tools.protoc -I./proto --python_out=/app/pb --grpc_python_out=/app/pb ./proto/vuelos.proto

# Variable de entorno para imports
ENV PYTHONPATH="/app:/app/pb:${PYTHONPATH}"

EXPOSE 50051

CMD ["python", "server.py"]