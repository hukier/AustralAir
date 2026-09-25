import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np

# Configuración del experimento
URL = "http://localhost:8000/v1/vuelos"
API_KEY = "secreto-australair-2026"
TOTAL_REQUESTS = 100
CONCURRENCY = 10

def realizar_peticion():
    req = urllib.request.Request(URL, headers={"X-API-Key": API_KEY})
    t_inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            codigo = resp.getcode()
    except urllib.error.HTTPError as e:
        codigo = e.code
    except Exception:
        codigo = 504  # Timeout o fallo de red local
    t_fin = time.perf_counter()
    latencia_ms = (t_fin - t_inicio) * 1000.0
    return codigo, latencia_ms

def ejecutar_prueba():
    print(f"\nDisparando {TOTAL_REQUESTS} peticiones hacia {URL} (concurrencia: {CONCURRENCY})...")
    latencias = []
    conteo_estados = {}

    t_global_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futuros = [executor.submit(realizar_peticion) for _ in range(TOTAL_REQUESTS)]
        for f in futuros:
            codigo, latencia = f.result()
            latencias.append(latencia)
            conteo_estados[codigo] = conteo_estados.get(codigo, 0) + 1
    t_global_fin = time.perf_counter()

    duracion_total = t_global_fin - t_global_inicio
    throughput = TOTAL_REQUESTS / duracion_total

    latencias.sort()
    p50 = np.percentile(latencias, 50)
    p95 = np.percentile(latencias, 95)
    p99 = np.percentile(latencias, 99)

    print("\n--- RESULTADOS DEL ESCENARIO ---")
    print(f"Duración total: {duracion_total:.2f} s")
    print(f"Throughput: {throughput:.2f} req/s")
    print(f"Códigos HTTP: {conteo_estados}")
    print(f"Latencia p50: {p50:.2f} ms")
    print(f"Latencia p95: {p95:.2f} ms")
    print(f"Latencia p99: {p99:.2f} ms")
    print("--------------------------------\n")

if __name__ == "__main__":
    ejecutar_prueba()