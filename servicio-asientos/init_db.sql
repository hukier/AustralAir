-- mapeado a db-asientos --

CREATE TABLE IF NOT EXISTS vuelos (
    vuelo_id VARCHAR(50) PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL,
    origen VARCHAR(10) NOT NULL,
    destino VARCHAR(10) NOT NULL,
    capacidad_total INT NOT NULL,
    asientos_disponibles INT NOT NULL
);

INSERT INTO vuelos (vuelo_id, codigo, origen, destino, capacidad_total, asientos_disponibles)
VALUES 
    ('1', 'AU-102', 'CCP', 'SCL', 150, 150),
    ('2', 'AU-205', 'SCL', 'ANF', 180, 180)
ON CONFLICT (vuelo_id) DO NOTHING;