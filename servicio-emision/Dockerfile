FROM python:3.11-slim

WORKDIR /app

COPY servicio-emision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servicio-emision/src/ ./src/

ENV PYTHONPATH="/app"

EXPOSE 8002

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002"]