-- Etapa 2: ingresos extraordinarios, inicio de ingresos recurrentes y categorías base.

ALTER TABLE transactions ADD COLUMN extraordinario INTEGER NOT NULL DEFAULT 0
    CHECK (extraordinario IN (0, 1));

-- Primer día (YYYY-MM-DD) desde el que se generan los ingresos de un recurrente.
ALTER TABLE recurring_incomes ADD COLUMN desde TEXT;

INSERT INTO categories (nombre) VALUES
    ('Comida'),
    ('Supermercado'),
    ('Transporte'),
    ('Servicios'),
    ('Suscripciones'),
    ('Salud'),
    ('Entretenimiento'),
    ('Otros');
