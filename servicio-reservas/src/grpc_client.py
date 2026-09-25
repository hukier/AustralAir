import os
import grpc
from datetime import datetime, timezone
from fastapi import HTTPException, status

import vuelos_pb2
import vuelos_pb2_grpc
from .schemas import CodigoErrorEnum

ASIENTOS_GRPC_HOST = os.getenv("ASIENTOS_GRPC_HOST", "servicio-asientos:50051")

class AsientosGRPCClient:
    def __init__(self):
        self.host = ASIENTOS_GRPC_HOST
        self.channel = grpc.insecure_channel(self.host)
        self.stub = vuelos_pb2_grpc.AsientosServiceStub(self.channel)

    def _obtener_stub(self):
        # Canal inseguro adecuado para redes privadas internas Docker (Requisito T4)
        return self.stub

    def _manejar_error_grpc(self, e: grpc.RpcError):
        """Traduce fallas de conexión o caídas del servicio gRPC a HTTP 503 (Requisito T7)."""
        codigo_grpc = e.code()
        
        if codigo_grpc in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "codigo": CodigoErrorEnum.SERVICIO_NO_DISPONIBLE.value,
                    "detalle": "El servicio interno de Asientos no se encuentra disponible o agotó el tiempo de espera.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
        
        # Cualquier otra falla interna no controlada
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "codigo": CodigoErrorEnum.ERROR_INTERNO.value,
                "detalle": f"Falla en la comunicación RPC interna: {e.details()}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    def listar_vuelos(self):
        """Consulta todos los vuelos programados en Asientos."""
        try:
            stub = self._obtener_stub()
            request = vuelos_pb2.ListarVuelosRequest()
            response = stub.ListarVuelos(request, timeout=3.0)
            return response.vuelos
        except grpc.RpcError as e:
            self._manejar_error_grpc(e)

    def consultar_vuelo(self, vuelo_id: str):
        """Consulta un vuelo específico y su disponibilidad en Asientos."""
        try:
            stub = self._obtener_stub()
            request = vuelos_pb2.ConsultarVueloRequest(vuelo_id=vuelo_id)
            response = stub.ConsultarVuelo(request, timeout=3.0)
            return response
        except grpc.RpcError as e:
            self._manejar_error_grpc(e)

    def reservar_asiento(self, vuelo_id: str, cantidad: int = 1):
        """Solicita el descuento atómico de un cupo en Asientos."""
        try:
            stub = self._obtener_stub()
            request = vuelos_pb2.ModificarCupoRequest(vuelo_id=vuelo_id, cantidad=cantidad)
            response = stub.ReservarAsiento(request, timeout=3.0)
            return response
        except grpc.RpcError as e:
            self._manejar_error_grpc(e)

    def liberar_asiento(self, vuelo_id: str, cantidad: int = 1):
        """Solicita la restitución de un cupo en Asientos por cancelación."""
        try:
            stub = self._obtener_stub()
            request = vuelos_pb2.ModificarCupoRequest(vuelo_id=vuelo_id, cantidad=cantidad)
            response = stub.LiberarAsiento(request, timeout=3.0)
            return response
        except grpc.RpcError as e:
            self._manejar_error_grpc(e)

cliente_asientos = AsientosGRPCClient()