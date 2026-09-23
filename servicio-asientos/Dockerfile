FROM python:3.11-slim

WORKDIR /app

# Instalamos las librerías directamente para asegurar que no falte nada
RUN pip install --no-cache-dir grpcio==1.59.0 grpcio-tools==1.59.0 psycopg2-binary==2.9.9

# Copiamos el código y la carpeta proto
COPY . .

# Creamos el directorio para el código generado
RUN mkdir -p /app/pb

# Generamos el código gRPC usando la carpeta ./proto local
RUN python -m grpc_tools.protoc -I./proto --python_out=/app/pb --grpc_python_out=/app/pb ./proto/vuelos.proto

CMD ["python", "server.py"]