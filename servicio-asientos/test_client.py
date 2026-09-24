#Test para comprobar logica: conectarsea al servidor local-> listar vuelos, reservar asientos y luego intentar forzar una sobreventa 


import sys
import os
import grpc

# Importar los archivos autogenerados de gRPC
sys.path.append(os.path.join(os.path.dirname(__file__), 'pb'))
import vuelos_pb2
import vuelos_pb2_grpc

def run():
    # Conectarse al servidor gRPC
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = vuelos_pb2_grpc.AsientosServiceStub(channel)

        print("--- 1. Listando Vuelos Iniciales ---")
        respuesta_lista = stub.ListarVuelos(vuelos_pb2.ListarVuelosRequest())
        for v in respuesta_lista.vuelos:
            print(f"Vuelo: {v.codigo} | Ruta: {v.origen}-{v.destino} | Disponibles: {v.asientos_disponibles}/{v.capacidad_total}")

        print("\n--- 2. Intentando reservar 2 asientos (AU-102) ---")
        req_reserva = vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=2)
        resp_reserva = stub.ReservarAsiento(req_reserva)
        print(f"Éxito: {resp_reserva.exito} | Mensaje: {resp_reserva.mensaje} | Restantes: {resp_reserva.asientos_restantes}")

        print("\n--- 3. Intentando reservar 200 asientos (Falla por sobreventa) ---")
        req_sobreventa = vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=200)
        resp_sobreventa = stub.ReservarAsiento(req_sobreventa)
        print(f"Éxito: {resp_sobreventa.exito} | Mensaje: {resp_sobreventa.mensaje} | Restantes: {resp_sobreventa.asientos_restantes}")

if __name__ == '__main__':
    run()