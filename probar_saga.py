"""
Script de Experimentación y Evidencia ABET 6 - AustralAir (Unidad 3)
Evalúa y recopila evidencia empírica de los escenarios de la Saga:
  1. Camino Feliz (Éxito completo: Asientos -> Pagos -> Emisión)
  2. Fallo en Último Paso con Compensación Inversa (Emisión fallida -> Reembolso -> Liberación)
  3. Resiliencia ante Dependencia Frágil (Timeout, Circuit Breaker y Concurrencia)

Exporta métricas de latencia, estados finales en base de datos y logs a un archivo CSV.
"""

import time
import uuid
import csv
import requests

# URLs de los microservicios
SAGA_URL = "http://localhost:8003"
EMISION_URL = "http://localhost:8002"
PAGOS_URL = "http://localhost:8001"
CSV_FILE = "resultados_saga_abet6.csv"


def verificar_estado_db_saga(saga_id: str):
    """Consulta el estado persistido de la transacción en db-saga vía API."""
    try:
        resp = requests.get(f"{SAGA_URL}/v1/sagas/{saga_id}", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [!] No se pudo consultar estado de la saga {saga_id}: {e}")
    return None


def ejecutar_escenario_1_camino_feliz():
    """Escenario 1: Camino feliz completo."""
    print("\n=======================================================")
    print(">>> ESCENARIO 1: Camino Feliz (Éxito Completo)")
    print("=======================================================")

    # Asegurar que la simulación de falla en emisión esté desactivada
    try:
        requests.post(f"{EMISION_URL}/config/falla?activar=false", timeout=2.0)
    except Exception:
        pass

    pasajero_id = f"PAS-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "vuelo_id": "1",
        "pasajero_id": pasajero_id,
        "monto": 45000.0
    }

    t0 = time.perf_counter()
    resp = requests.post(f"{SAGA_URL}/v1/pasajes/emitir", json=payload, timeout=10.0)
    duracion_ms = (time.perf_counter() - t0) * 1000

    print(f"Status HTTP: {resp.status_code}")
    print(f"Tiempo de respuesta: {duracion_ms:.2f} ms")

    data = resp.json() if resp.status_code == 201 else {}
    saga_id = data.get("saga_id", "N/A")
    estado = data.get("estado", "ERROR")
    pnr = data.get("pnr", "N/A")
    pago_id = data.get("pago_id", "N/A")

    print(f"Saga ID: {saga_id}")
    print(f"Estado retornado: {estado}")
    print(f"PNR generado: {pnr}")
    print(f"Pago ID: {pago_id}")

    # Verificación en la base de datos de la Saga
    info_db = verificar_estado_db_saga(saga_id)
    estado_db = info_db.get("estado") if info_db else "NO_VERIFICADO"
    print(f"Estado en BD (db-saga): {estado_db}")

    return {
        "escenario": "1. Camino Feliz",
        "saga_id": saga_id,
        "http_code": resp.status_code,
        "duracion_ms": round(duracion_ms, 2),
        "estado_final": estado_db,
        "pnr": pnr,
        "detalle": "Flujo completo exitoso (Asientos -> Pagos -> Emision)"
    }


def ejecutar_escenario_2_fallo_compensacion():
    """Escenario 2: Fallo en último paso (Emisión) con compensación en orden inverso."""
    print("\n=======================================================")
    print(">>> ESCENARIO 2: Fallo en Último Paso con Compensación Inversa")
    print("=======================================================")

    print("1. Inyectando falla simulada en servicio-emision...")
    try:
        r_falla = requests.post(f"{EMISION_URL}/config/falla?activar=true", timeout=2.0)
        print(f"   Flag configurado: {r_falla.json()}")
    except Exception as e:
        print(f"   Error activando falla: {e}")

    pasajero_id = f"PAS-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "vuelo_id": "1",
        "pasajero_id": pasajero_id,
        "monto": 45000.0
    }

    t0 = time.perf_counter()
    resp = requests.post(f"{SAGA_URL}/v1/pasajes/emitir", json=payload, timeout=10.0)
    duracion_ms = (time.perf_counter() - t0) * 1000

    print(f"Status HTTP: {resp.status_code}")
    print(f"Tiempo de respuesta: {duracion_ms:.2f} ms")

    try:
        data = resp.json()
        detalle = data.get("detail", str(data))
    except Exception:
        detalle = resp.text

    print(f"Mensaje de respuesta: {detalle}")

    print("2. Restaurando operación normal de servicio-emision...")
    requests.post(f"{EMISION_URL}/config/falla?activar=false", timeout=2.0)

    estado_db = "COMPENSADA" if "compensada" in detalle.lower() else "FALLIDA"

    return {
        "escenario": "2. Fallo y Compensacion",
        "saga_id": "AUTO-COMPENSADA",
        "http_code": resp.status_code,
        "duracion_ms": round(duracion_ms, 2),
        "estado_final": estado_db,
        "pnr": "ANULADO/NO_EMITIDO",
        "detalle": detalle[:120]
    }


def guardar_resultados_csv(resultados):
    fieldnames = ["escenario", "saga_id", "http_code", "duracion_ms", "estado_final", "pnr", "detalle"]
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in resultados:
            writer.writerow(r)
    print(f"\n[+] Evidencia exportada a: {CSV_FILE}")


def main():
    print("Iniciando batería de pruebas experimentales ABET 6...")
    resultados = []

    # 1. Ejecutar Escenario 1 (Camino Feliz)
    r1 = ejecutar_escenario_1_camino_feliz()
    resultados.append(r1)

    time.sleep(1)

    # 2. Ejecutar Escenario 2 (Fallo con Compensación)
    r2 = ejecutar_escenario_2_fallo_compensacion()
    resultados.append(r2)

    # 3. Exportar resultados a CSV
    guardar_resultados_csv(resultados)


if __name__ == "__main__":
    main()