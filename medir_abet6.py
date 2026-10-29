"""
=============================================================================
AustralAir - Script de Experimentación y Benchmarking ABET 6
=============================================================================
Mide latencias (p50, p95, p99), Throughput y distribución de códigos HTTP.
Guarda los datos crudos de cada petición en 'resultados_abet6_crudos.csv'.
Soporta consultas (GET) y creación de reservas (POST).
=============================================================================
"""

import sys
import os
import time
import json
import csv
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

try:
    import numpy as np
    def calcular_percentil(valores, p):
        return float(np.percentile(valores, p))
except ImportError:
    def calcular_percentil(valores, p):
        if not valores:
            return 0.0
        s = sorted(valores)
        k = (len(s) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c < len(s):
            return s[f] + (k - f) * (s[c] - s[f])
        return s[f]

BASE_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "secreto-australair-2026")
TOTAL_REQUESTS = 100
CONCURRENCY = 10
REPETICIONES = 3
CSV_FILE = "resultados_abet6_crudos.csv"


def inicializar_csv():
    """Crea el archivo CSV con sus encabezados si no existe."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "escenario", "repeticion", "operacion", 
                "peticion_num", "codigo_http", "latencia_ms"
            ])


def registrar_muestra_csv(escenario, repeticion, operacion, req_num, codigo, latencia_ms):
    """Escribe cada petición individual en el archivo CSV de datos crudos."""
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            round(time.time(), 3), escenario, repeticion, operacion,
            req_num, codigo, round(latencia_ms, 2)
        ])


def obtener_pasajero_id():
    """Obtiene un ID de pasajero existente o crea uno de prueba para el test POST."""
    url = f"{BASE_URL}/v1/pasajeros"
    req = urllib.request.Request(url, headers={"X-API-Key": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                p = data[0]
                return str(p.get("id") or p.get("pasajero_id") or "1")
    except Exception:
        pass

    nuevo_pasajero = json.dumps({
        "rut": "18945632-1",
        "nombre_completo": "Pasajero Benchmark ABET6",
        "email": "benchmark@australair.com"
    }).encode("utf-8")
    
    req_post = urllib.request.Request(
        url,
        data=nuevo_pasajero,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req_post, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("id") or data.get("pasajero_id") or "1")
    except Exception:
        return "1"


def realizar_peticion_get():
    url = f"{BASE_URL}/v1/vuelos"
    req = urllib.request.Request(url, headers={"X-API-Key": API_KEY})
    t_inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            codigo = resp.getcode()
    except urllib.error.HTTPError as e:
        codigo = e.code
    except Exception:
        codigo = 504
    t_fin = time.perf_counter()
    latencia_ms = (t_fin - t_inicio) * 1000.0
    return codigo, latencia_ms


def realizar_peticion_post(pasajero_id):
    url = f"{BASE_URL}/v1/reservas"
    payload = json.dumps({
        "pasajero_id": pasajero_id,
        "vuelo_id": "1"
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    t_inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            codigo = resp.getcode()
    except urllib.error.HTTPError as e:
        codigo = e.code
    except Exception:
        codigo = 504
    t_fin = time.perf_counter()
    latencia_ms = (t_fin - t_inicio) * 1000.0
    return codigo, latencia_ms


def ejecutar_corrida(escenario, operacion, repeticion, pasajero_id=None):
    for _ in range(3):
        try:
            req_warm = urllib.request.Request(f"{BASE_URL}/health")
            with urllib.request.urlopen(req_warm, timeout=2.0):
                pass
        except Exception:
            pass

    latencias = []
    conteo_estados = {}

    t_global_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        if operacion == "GET":
            futuros = [executor.submit(realizar_peticion_get) for _ in range(TOTAL_REQUESTS)]
        else:
            futuros = [executor.submit(realizar_peticion_post, pasajero_id) for _ in range(TOTAL_REQUESTS)]

        for req_num, f in enumerate(futuros, 1):
            codigo, latencia = f.result()
            latencias.append(latencia)
            conteo_estados[codigo] = conteo_estados.get(codigo, 0) + 1
            registrar_muestra_csv(escenario, repeticion, operacion, req_num, codigo, latencia)

    t_global_fin = time.perf_counter()
    duracion_total = t_global_fin - t_global_inicio
    throughput = TOTAL_REQUESTS / duracion_total if duracion_total > 0 else 0.0

    p50 = calcular_percentil(latencias, 50)
    p95 = calcular_percentil(latencias, 95)
    p99 = calcular_percentil(latencias, 99)

    return {
        "duracion": duracion_total,
        "throughput": throughput,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "estados": conteo_estados
    }


def main():
    escenario = sys.argv[1] if len(sys.argv) > 1 else "Escenario 1: Base"
    operacion = sys.argv[2].upper() if len(sys.argv) > 2 else "GET"

    if operacion not in ["GET", "POST"]:
        print(f"[ERROR] Operación '{operacion}' no válida. Use 'GET' o 'POST'.")
        sys.exit(1)

    inicializar_csv()

    pasajero_id = None
    if operacion == "POST":
        pasajero_id = obtener_pasajero_id()

    url_objetivo = f"{BASE_URL}/v1/vuelos" if operacion == "GET" else f"{BASE_URL}/v1/reservas"
    print(f"\n==============================================================")
    print(f" BENCHMARK ABET 6: {escenario} | Operación: {operacion}")
    print(f" URL: {url_objetivo}")
    print(f" Concurrencia: {CONCURRENCY} | Peticiones: {TOTAL_REQUESTS} | Repeticiones: {REPETICIONES}")
    print(f" Archivo CSV crudo: {CSV_FILE}")
    print(f"==============================================================")

    resultados_corridas = []
    for r in range(1, REPETICIONES + 1):
        print(f"\nDisparando Corrida {r}/{REPETICIONES}...")
        res = ejecutar_corrida(escenario, operacion, r, pasajero_id)
        resultados_corridas.append(res)
        
        print(f"  Duración: {res['duracion']:.2f} s | Throughput: {res['throughput']:.2f} req/s")
        print(f"  p50: {res['p50']:.2f} ms | p95: {res['p95']:.2f} ms | p99: {res['p99']:.2f} ms")
        print(f"  Códigos HTTP: {res['estados']}")
        time.sleep(1)

    avg_tp = sum(r["throughput"] for r in resultados_corridas) / REPETICIONES
    avg_p50 = sum(r["p50"] for r in resultados_corridas) / REPETICIONES
    avg_p95 = sum(r["p95"] for r in resultados_corridas) / REPETICIONES
    avg_p99 = sum(r["p99"] for r in resultados_corridas) / REPETICIONES

    print("\n---------------- CONSOLIDADO FINAL ----------------")
    print(f"Escenario: {escenario} ({operacion})")
    print(f"Throughput promedio: {avg_tp:.2f} req/s")
    print(f"Latencia p50 promedio: {avg_p50:.2f} ms")
    print(f"Latencia p95 promedio: {avg_p95:.2f} ms")
    print(f"Latencia p99 promedio: {avg_p99:.2f} ms")
    print(f"Muestras individuales guardadas en '{CSV_FILE}'")
    print("---------------------------------------------------\n")


if __name__ == "__main__":
    main()
