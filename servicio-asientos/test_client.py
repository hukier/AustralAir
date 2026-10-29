"""
=============================================================================
Batería de Pruebas de Integración gRPC: test_client.py
Microservicio: servicio-asientos (AustralAir)
=============================================================================
Ejecuta 8 pruebas con aserciones estrictas sobre un vuelo de prueba aislado
('TEST-99') para evitar modificar o corromper los datos del inventario real.
=============================================================================
"""

import sys
import os
import psycopg2
import grpc

# Importar stubs gRPC
sys.path.append(os.path.join(os.path.dirname(__file__), 'pb'))
import vuelos_pb2
import vuelos_pb2_grpc

TEST_VUELO_ID = "TEST-99"
TEST_CODIGO = "AU-TEST99"
CAPACIDAD_INICIAL = 10


def get_db_connection():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://usuario_asientos:password_asientos_segura@db-asientos:5432/australair_asientos"
    )
    return psycopg2.connect(db_url)


def setup_test_flight():
    """Crea o reinicia el vuelo temporal aislado para pruebas."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vuelos WHERE vuelo_id = %s;", (TEST_VUELO_ID,))
            cur.execute(
                """
                INSERT INTO vuelos (vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles)
                VALUES (%s, %s, 'CCP', 'SCL', %s, %s);
                """,
                (TEST_VUELO_ID, TEST_CODIGO, CAPACIDAD_INICIAL, CAPACIDAD_INICIAL)
            )
        conn.commit()


def teardown_test_flight():
    """Limpia el vuelo temporal para no dejar residuos en la base de datos."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM vuelos WHERE vuelo_id = %s;", (TEST_VUELO_ID,))
            conn.commit()
    except Exception as e:
        print(f"[WARN] Error en teardown: {e}")


def run_tests():
    host = os.environ.get("GRPC_HOST", "localhost:50051")
    print(f"\n==========================================================")
    print(f" Iniciando batería de pruebas gRPC en: {host}")
    print(f" Vuelo temporal aislado: {TEST_VUELO_ID} (Capacidad: {CAPACIDAD_INICIAL})")
    print(f"==========================================================\n")

    setup_test_flight()

    try:
        with grpc.insecure_channel(host) as channel:
            stub = vuelos_pb2_grpc.AsientosServiceStub(channel)

            # -------------------------------------------------------------
            # T1: Listar vuelos existentes
            # -------------------------------------------------------------
            print("[TEST 1] Listar vuelos")
            resp = stub.ListarVuelos(vuelos_pb2.ListarVuelosRequest())
            assert len(resp.vuelos) > 0, "La lista de vuelos no debe estar vacía"
            assert any(v.vuelo_id == TEST_VUELO_ID for v in resp.vuelos), "El vuelo de prueba debe figurar en el catálogo"
            print(f"  -> OK: {len(resp.vuelos)} vuelos recuperados.")

            # -------------------------------------------------------------
            # T2: Consultar vuelo de prueba existente
            # -------------------------------------------------------------
            print("[TEST 2] Consultar disponibilidad de vuelo válido")
            vuelo = stub.ConsultarVuelo(vuelos_pb2.ConsultarVueloRequest(vuelo_id=TEST_VUELO_ID))
            assert vuelo.vuelo_id == TEST_VUELO_ID, "El ID del vuelo debe coincidir"
            assert vuelo.codigo == TEST_CODIGO, "El código comercial debe coincidir"
            assert vuelo.asientos_disponibles == CAPACIDAD_INICIAL, "Debe tener 10 asientos disponibles"
            print(f"  -> OK: Vuelo {vuelo.codigo} con {vuelo.asientos_disponibles} asientos.")

            # -------------------------------------------------------------
            # T3: Consultar vuelo inexistente (debe retornar StatusCode.NOT_FOUND)
            # -------------------------------------------------------------
            print("[TEST 3] Consultar vuelo inexistente")
            try:
                stub.ConsultarVuelo(vuelos_pb2.ConsultarVueloRequest(vuelo_id="VUELO-FANTASMA-999"))
                assert False, "Se esperaba excepción gRPC NOT_FOUND"
            except grpc.RpcError as e:
                assert e.code() == grpc.StatusCode.NOT_FOUND, f"Código incorrecto: {e.code()}"
                print(f"  -> OK: Capturada excepción {e.code().name} correctamente.")

            # -------------------------------------------------------------
            # T4: Reserva válida (decremento atómico)
            # -------------------------------------------------------------
            print("[TEST 4] Reserva atómica válida (descontar 3 asientos)")
            res = stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id=TEST_VUELO_ID, cantidad=3))
            assert res.exito is True, "La reserva debe ser exitosa"
            assert res.asientos_restantes == 7, f"Deben quedar 7 asientos, quedaron {res.asientos_restantes}"
            assert res.codigo_error == vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
            print(f"  -> OK: Reserva confirmada. Asientos restantes: {res.asientos_restantes}")

            # -------------------------------------------------------------
            # T5: Prevención de sobreventa (solicitar más de los disponibles)
            # -------------------------------------------------------------
            print("[TEST 5] Prevención de sobreventa (intentar reservar 50 asientos)")
            res_sobreventa = stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id=TEST_VUELO_ID, cantidad=50))
            assert res_sobreventa.exito is False, "La sobreventa debe ser rechazada"
            assert res_sobreventa.codigo_error == vuelos_pb2.SIN_ASIENTOS_DISPONIBLES
            assert res_sobreventa.asientos_restantes == 7, "El inventario no debe alterarse tras sobreventa fallida"
            print(f"  -> OK: Sobreventa rechazada. Mensaje: '{res_sobreventa.mensaje}'.")

            # -------------------------------------------------------------
            # T6: Argumento inválido en reserva (cantidad <= 0)
            # -------------------------------------------------------------
            print("[TEST 6] Validación de argumentos inválidos (cantidad = 0)")
            try:
                stub.ReservarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id=TEST_VUELO_ID, cantidad=0))
                assert False, "Se esperaba StatusCode.INVALID_ARGUMENT"
            except grpc.RpcError as e:
                assert e.code() == grpc.StatusCode.INVALID_ARGUMENT, f"Código inesperado: {e.code()}"
                print(f"  -> OK: Rechazado con excepción {e.code().name}.")

            # -------------------------------------------------------------
            # T7: Liberación atómica de asientos
            # -------------------------------------------------------------
            print("[TEST 7] Liberación válida (devolver los 3 asientos reservados)")
            lib = stub.LiberarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id=TEST_VUELO_ID, cantidad=3))
            assert lib.exito is True, "La liberación debe ser exitosa"
            assert lib.asientos_restantes == 10, f"Deben haber 10 asientos, hay {lib.asientos_restantes}"
            print(f"  -> OK: Asientos liberados exitosamente. Disponibles: {lib.asientos_restantes}")

            # -------------------------------------------------------------
            # T8: Liberación excesiva que supera capacidad máxima
            # -------------------------------------------------------------
            print("[TEST 8] Rechazo de liberación excesiva por sobre la capacidad física")
            lib_exceso = stub.LiberarAsiento(vuelos_pb2.ModificarCupoRequest(vuelo_id=TEST_VUELO_ID, cantidad=15))
            assert lib_exceso.exito is False, "La liberación que supera la capacidad no debe aceptarse silenciosamente"
            assert lib_exceso.asientos_restantes == 10, "El inventario debe mantenerse en 10"
            print(f"  -> OK: Operación rechazada. Mensaje: '{lib_exceso.mensaje}'.")

        print("\n==========================================================")
        print(" RESULTADO: 8/8 CASOS PASARON CON ASERCIONES VERIFICADAS")
        print("==========================================================\n")

    finally:
        teardown_test_flight()
        print("[INFO] Vuelo temporal 'TEST-99' eliminado de db-asientos. Base de datos limpia.")


if __name__ == "__main__":
    run_tests()