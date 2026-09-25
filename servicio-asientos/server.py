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

# Configuración del path para importar los módulos generados por protoc
sys.path.append(os.path.join(os.path.dirname(__file__), 'pb'))
import vuelos_pb2
import vuelos_pb2_grpc

class AsientosService(vuelos_pb2_grpc.AsientosServiceServicer):
    #Servicio gRPC que implementa los endpoints de consulta y mutación atómica del inventario de vuelos
    
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL") #cadena de conexión inyectada desde las variables de entorno de Docker Compose

    def get_db_connection(self): #establece una conexión transaccional con la base de datos db-asientos
        return psycopg2.connect(self.db_url)

    def ConsultarVuelo(self, request, context):
        #consulta los detalles y disponibilidad de un vuelo particular por su vuelo_id. Si el vuelo no existe, propaga el código de estado gRPC NOT_FOUND
        try:

            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles FROM vuelos WHERE vuelo_id = %s",
                        (request.vuelo_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return vuelos_pb2.VueloResponse(
                            vuelo_id=row[0], codigo=row[1], origen=row[2],
                            destino=row[3], capacidad_total=row[4], asientos_disponibles=row[5]
                        )
                    else: # VUELO NO REGISTRADO EN EL INVENTARIO...
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details('Vuelo no encontrado')
                        return vuelos_pb2.VueloResponse()
        except Exception as e: #captura errores no controlados y mapeo a StatusCode.INTERNAL
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.VueloResponse()

    def ListarVuelos(self, request, context):
        #retorna la colección completa de vuelos disponibles en el catálogo. Incluye inyección de latencia sintética para experimentación de resiliencia (ABET 6)
        try:
            # --- Inyección de latencia para ABET 6 (lee la variable de entorno para simular degradación de red/servicio) ---
            latencia = float(os.environ.get("LATENCIA_SIMULADA", "0.0"))
            if latencia > 0:
                time.sleep(latencia)
            # ----------------------------------------

            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles FROM vuelos")
                    filas = cur.fetchall()
                    
                    respuesta = vuelos_pb2.ListarVuelosResponse()
                    for f in filas:
                        vuelo = respuesta.vuelos.add()
                        vuelo.vuelo_id = f[0]
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
        #decrementa de manera atomica el cupo de asientos disponibles para un vuelo. !!garantia de consistencia: usa una condición SQL WHERE asientos_disponibles >= %s para prevenir sobreventa ante múltiples peticiones concurrentes sin necesidad de bloqueos de tabla pesados
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur: # INTENTO DE ACTUALIZACION ATOMICA CON GUARDA DE SUFICIENCIA
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
                    conn.commit()
                    
                    if row: #CUPO RESERVADO CON EXITO
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=True, mensaje="Reserva confirmada",
                            asientos_restantes=row[0], codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                        )
                    else: #NO SE ACTUALIZÓ NINGUNA FILA -> VERIFICAR LA CAUSA (no existe el vuelo o no hay cupo)
                        cur.execute("SELECT asientos_disponibles FROM vuelos WHERE vuelo_id = %s", (request.vuelo_id,))
                        vuelo = cur.fetchone()
                        if vuelo:
                            return vuelos_pb2.ModificarCupoResponse(
                                exito=False, mensaje="Sin asientos suficientes",
                                asientos_restantes=vuelo[0], codigo_error=vuelos_pb2.SIN_ASIENTOS_DISPONIBLES
                            )
                        else:
                            return vuelos_pb2.ModificarCupoResponse(
                                exito=False, mensaje="Vuelo no encontrado",
                                asientos_restantes=0, codigo_error=vuelos_pb2.VUELO_NO_ENCONTRADO
                            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.ModificarCupoResponse(exito=False)

    def LiberarAsiento(self, request, context):
        #incrementa de manera tomica los asientos disponibles(rollback o cancelación) !!limite capacidad fisica: aplica la funcion LEAST(asientos_disponibles + %s, capacidad_total) para evitar que devoluciones repetidas superen la capacidad física real del avión
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE vuelos 
                        SET asientos_disponibles = LEAST(asientos_disponibles + %s, capacidad_total)
                        WHERE vuelo_id = %s
                        RETURNING asientos_disponibles
                        """,
                        (request.cantidad, request.vuelo_id)
                    )
                    row = cur.fetchone()
                    conn.commit()
                    
                    if row:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=True, mensaje="Asiento liberado",
                            asientos_restantes=row[0], codigo_error=vuelos_pb2.CODIGO_ERROR_NO_ESPECIFICADO
                        )
                    else:
                        return vuelos_pb2.ModificarCupoResponse(
                            exito=False, mensaje="Vuelo no encontrado",
                            asientos_restantes=0, codigo_error=vuelos_pb2.VUELO_NO_ENCONTRADO
                        )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return vuelos_pb2.ModificarCupoResponse(exito=False)

def serve():
    # Inicializa el servidor gRPC configurando un ThreadPoolExecutor para procesar hasta 10 llamadas concurrentes y vincula el puerto de escucha.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    vuelos_pb2_grpc.add_AsientosServiceServicer_to_server(AsientosService(), server)
    port = os.environ.get("PORT", "50051")
    server.add_insecure_port(f'[::]:{port}')
    print(f"Servidor de Asientos gRPC iniciando en el puerto {port}...")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    time.sleep(2) #breve pausa para asegurar disponibilidad del motor de base de datos antes de enlazar el puerto
    serve()