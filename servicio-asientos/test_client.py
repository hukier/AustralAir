#Test para comprobar logica (actualización para tener todos los casos favorables y todos los casos borde)


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

        print("\n==================================================")
        print(" PRUEBAS: MICROSERVICIO DE ASIENTOS")

        # 1. HAPPY PATH: Listar todos los vuelos
        print("\n[TEST 1] Listar vuelos iniciales (Happy Path)")
        resp_lista = stub.ListarVuelos(vuelos_pb2.ListarVuelosRequest())
        for v in resp_lista.vuelos:
            print(f"  -> {v.codigo} ({v.origen}-{v.destino}) | Disponibles: {v.asientos_disponibles}/{v.capacidad_total}")

        # 2. HAPPY PATH: Consultar un vuelo existente
        print("\n[TEST 2] Consultar vuelo existente (ID: '1')")
        try:
            vuelo = stub.ConsultarVuelo(vuelos_pb2.ConsultarVueloRequest(vuelo_id='1'))
            print(f"  -> Éxito: Encontrado {vuelo.codigo} con {vuelo.asientos_disponibles} asientos.")
        except grpc.RpcError as e:
            print(f"  -> Falló inesperadamente: {e.details()}")

        # 3. CASO LÍMITE: Consultar un vuelo que no existe
        print("\n[TEST 3] Consultar vuelo inexistente (ID: '999')")
        try:
            stub.ConsultarVuelo(vuelos_pb2.ConsultarVueloRequest(vuelo_id='999'))
        except grpc.RpcError as e:
            print(f"  -> Error capturado correctamente: Código {e.code().name} - {e.details()}")

        # 4. HAPPY PATH: Reservar asientos válidos
        print("\n[TEST 4] Reservar 5 asientos en AU-102 (ID: '1')")
        resp = stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=5))
        print(f"  -> Éxito: {resp.exito} | {resp.mensaje} | Restantes: {resp.asientos_restantes}")

        # 5. CASO LÍMITE: Intentar sobreventa
        print("\n[TEST 5] Forzar sobreventa pidiendo 200 asientos en AU-102")
        resp = stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=200))
        print(f"  -> Éxito: {resp.exito} | {resp.mensaje} | Restantes: {resp.asientos_restantes}")

        # 6. CASO LÍMITE: Reservar en vuelo fantasma
        print("\n[TEST 6] Reservar en vuelo que no existe (ID: '999')")
        resp = stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id='999', cantidad=2))
        print(f"  -> Éxito: {resp.exito} | {resp.mensaje} | Restantes: {resp.asientos_restantes}")

        # 7. HAPPY PATH: Liberar/Cancelar una reserva
        print("\n[TEST 7] Liberar 2 asientos en AU-102 (de los 5 reservados antes)")
        resp = stub.LiberarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=2))
        print(f"  -> Éxito: {resp.exito} | {resp.mensaje} | Restantes: {resp.asientos_restantes}")

        # 8. CASO LÍMITE: Liberar más asientos de la capacidad total
        print("\n[TEST 8] Forzar liberación masiva (intentar devolver 100 asientos extra)")
        print("  (Debe topar en el máximo de capacidad total sin superarla gracias a LEAST en SQL)")
        resp = stub.LiberarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id='1', cantidad=100))
        print(f"  -> Éxito: {resp.exito} | {resp.mensaje} | Restantes: {resp.asientos_restantes}")
        
        print(" PRUEBAS FINALIZADAS")
        print("==================================================\n")

if __name__ == '__main__':
    run()