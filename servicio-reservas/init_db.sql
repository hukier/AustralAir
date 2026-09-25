CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS pasajeros (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rut VARCHAR(12) UNIQUE NOT NULL,
    nombre_completo VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Estado formal de la reserva segun el contrato OpenAPI
DO $$ BEGIN
    CREATE TYPE estado_reserva AS ENUM ('CONFIRMADA', 'CANCELADA');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Tabla de reservas
CREATE TABLE IF NOT EXISTS reservas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pasajero_id UUID NOT NULL REFERENCES pasajeros(id) ON DELETE RESTRICT,
    vuelo_id VARCHAR(50) NOT NULL,
    estado estado_reserva NOT NULL DEFAULT 'CONFIRMADA',
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reservas_vuelo_id ON reservas(vuelo_id);

-- Tabla para almacenar llaves de idempotencia
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key UUID PRIMARY KEY,
    response_code INT NOT NULL,
    response_body JSONB NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Datos semilla iniciales para desarrollo y pruebas
INSERT INTO pasajeros (id, rut, nombre_completo, email)
VALUES 
    ('e4eebc99-9c0b-4ef8-bb6d-6bb9bd380a55', '19876543-2', 'Camila Soto', 'camila.soto@email.com')
ON CONFLICT (rut) DO NOTHING;