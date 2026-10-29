"""
Implementación del servidor gRPC para la gestión atómica del inventario de asientos y catálogo de vuelos. 

Aspectos técnicos destacados:
- Persistencia aislada en PostgreSQL (db-asientos) bajo ADR-001
- Contrato gRPC / Protocol Buffers (AsientosService) bajo ADR-003
- Prevención de condiciones de carrera y sobreventa mediante SQL condicional
- Uso de función LEAST() para garantizar el tope físico de capacidad
- Inyección de latencia parametrizada para evaluación de resiliencia (ABET 6)
"""
import sys
import os
import time
from concurrent import futures
import psycopg2
import grpc

# Importar stubs generados en pb/
sys.path.append(os.path.join(os.path.dirname(__file__), 'pb'))
import vuelos_pb2
import vuelos_pb2_grpc


class AsientosService(vuelos_pb2_grpc.AsientosServiceServicer):
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL")

    def get_db_connection(self):
        return psycopg2.connect(self.db_url)

    def ConsultarVuelo(self, request, context):
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles 
                        FROM vuelos 
                        WHERE vuelo_id = %s
                        """,
                        (request.vuelo_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return vuelos_pb2.VueloResponse(
                            vuelo_id=str(row[0]),
                            codigo=row[1],
                            origen=row[2],
                            destino=row[3],
                            capacidad_total=row[4],
                            asientos_disponibles=row[5]
                        )
                    else:
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details("Vuelo no encontrado")
                        return vuelos_pb2.VueloResponse()
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.VueloResponse()

    def ListarVuelos(self, request, context):
        try:
            # Inyección de latencia para experimentación ABET 6
            latencia = float(os.environ.get("LATENCIA_SIMULADA", "0.0"))
            if latencia > 0:
                time.sleep(latencia)

            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles 
                        FROM vuelos 
                        ORDER BY vuelo_id ASC
                        """
                    )
                    filas = cur.fetchall()
                    
                    respuesta = vuelos_pb2.ListarVuelosResponse()
                    for f in filas:
                        vuelo = respuesta.vuelos.add()
                        vuelo.vuelo_id = str(f[0])
                        vuelo.codigo = f[1]
                        vuelo.origen = f[2]
                        vuelo.destino = f[3]
                        vuelo.capacidad_total = f[4]
                        vuelo.asientos_disponibles = f[5]
                    return respuesta
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.ListarVuelosResponse()

    def ReservarAsiento(self, request, context):
        # 1. Validación estricta de cantidad
        if request.cantidad <= 0:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("La cantidad a reservar debe ser mayor a 0")
            return vuelos_pb2.ModificarCupoResponse(
                exito=False,
                mensaje="Cantidad invalida",
                asientos_restantes=0,
                codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
            )

        conn = None
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cur:
                # 2. Descuento atómico con guarda de disponibilidad
                cur.execute(
                    """
                    UPDATE vuelos 
                    SET asientos_disponibles = asientos_disponibles - %s 
                    WHERE vuelo_id = %s AND asientos_disponibles >= %s
                    RETURNING asientos_disponibles
                    """,
                    (request.cantidad, request.vuelo_id, request.cantidad)
                )
                row = cur.fetchone()

                # 3. Protección anti-timeout: Si el cliente ya cortó por timeout, abortar descuento
                if not context.is_active():
                    conn.rollback()
                    return vuelos_pb2.ModificarCupoResponse(
                        exito=False,
                        mensaje="Llamada gRPC expirada o cancelada",
                        asientos_restantes=0,
                        codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                    )

                if row:
                    conn.commit()
                    return vuelos_pb2.ModificarCupoResponse(
                        exito=True,
                        mensaje="Reserva confirmada",
                        asientos_restantes=row[0],
                        codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                    )
                else:
                    # Determinar si el vuelo no existe o si no hay asientos suficientes
                    cur.execute("SELECT asientos_disponibles FROM vuelos WHERE vuelo_id = %s", (request.vuelo_id,))
                    vuelo = cur.fetchone()
                    conn.rollback()
                    if vuelo:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=False,
                            mensaje="Sin asientos suficientes",
                            asientos_restantes=vuelo[0],
                            codigo_error=vuelos_pb2.SIN_ASIENTOS_DISPONIBLES
                        )
                    else:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=False,
                            mensaje="Vuelo no encontrado",
                            asientos_restantes=0,
                            codigo_error=vuelos_pb2.VUELO_NO_ENCONTRADO
                        )
        except Exception as e:
            if conn:
                conn.rollback()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.ModificarCupoResponse(
                exito=False,
                mensaje=f"Error interno: {str(e)}",
                asientos_restantes=0,
                codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
            )
        finally:
            if conn:
                conn.close()

    def LiberarAsiento(self, request, context):
        # 1. Validación estricta de cantidad
        if request.cantidad <= 0:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("La cantidad a liberar debe ser mayor a 0")
            return vuelos_pb2.ModificarCupoResponse(
                exito=False,
                mensaje="Cantidad invalida",
                asientos_restantes=0,
                codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
            )

        conn = None
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cur:
                # 2. Guarda explícita sin LEAST(): no se permite superar la capacidad física
                cur.execute(
                    """
                    UPDATE vuelos 
                    SET asientos_disponibles = asientos_disponibles + %s 
                    WHERE vuelo_id = %s AND (asientos_disponibles + %s) <= capacidad_total
                    RETURNING asientos_disponibles
                    """,
                    (request.cantidad, request.vuelo_id, request.cantidad)
                )
                row = cur.fetchone()

                # 3. Protección anti-timeout
                if not context.is_active():
                    conn.rollback()
                    return vuelos_pb2.ModificarCupoResponse(
                        exito=False,
                        mensaje="Llamada gRPC expirada o cancelada",
                        asientos_restantes=0,
                        codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                    )

                if row:
                    conn.commit()
                    return vuelos_pb2.ModificarCupoResponse(
                        exito=True,
                        mensaje="Asiento liberado",
                        asientos_restantes=row[0],
                        codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                    )
                else:
                    cur.execute(
                        "SELECT capacidad_total, asientos_disponibles FROM vuelos WHERE vuelo_id = %s",
                        (request.vuelo_id,)
                    )
                    vuelo = cur.fetchone()
                    conn.rollback()
                    if vuelo:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=False,
                            mensaje="La liberacion excede la capacidad total del vuelo",
                            asientos_restantes=vuelo[1],
                            codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                        )
                    else:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=False,
                            mensaje="Vuelo no encontrado",
                            asientos_restantes=0,
                            codigo_error=vuelos_pb2.VUELO_NO_ENCONTRADO
                        )
        except Exception as e:
            if conn:
                conn.rollback()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.ModificarCupoResponse(
                exito=False,
                mensaje=f"Error interno: {str(e)}",
                asientos_restantes=0,
                codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
            )
        finally:
            if conn:
                conn.close()


def serve():
    puerto = os.environ.get("PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    vuelos_pb2_grpc.add_AsientosServiceServicer_to_server(AsientosService(), server)
    server.add_insecure_port(f"[::]:{puerto}")
    print(f"Servidor gRPC servicio-asientos activo en puerto {puerto}...")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    time.sleep(2)
    serve()