FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/pb
RUN python -m grpc_tools.protoc -I./proto --python_out=/app/pb --grpc_python_out=/app/pb ./proto/vuelos.proto

ENV PYTHONPATH="/app:/app/pb"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]