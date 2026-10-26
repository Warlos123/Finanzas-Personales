-- Esquema inicial. Montos en céntimos enteros (siempre positivos; el signo lo da `tipo`).
-- Fechas en TEXT ISO 8601 con offset (America/Costa_Rica = -06:00).

CREATE TABLE raw_events (
    id INTEGER PRIMARY KEY,
    fuente TEXT NOT NULL CHECK (fuente IN ('gmail_bcr', 'sms_4066', 'manual', 'csv')),
    contenido TEXT NOT NULL,
    recibido_en TEXT NOT NULL,
    hash TEXT NOT NULL,
    estado_parseo TEXT NOT NULL DEFAULT 'sin_procesar'
        CHECK (estado_parseo IN ('sin_procesar', 'ok', 'con_avisos', 'error')),
    detalle_parseo TEXT,
    procesado_en TEXT,
    creado_en TEXT NOT NULL,
    UNIQUE (fuente, hash)
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('tarjeta', 'sinpe', 'efectivo', 'otra')),
    ultimos4 TEXT,
    moneda TEXT NOT NULL DEFAULT 'CRC' CHECK (moneda IN ('CRC', 'USD'))
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    padre_id INTEGER REFERENCES categories (id)
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    raw_event_id INTEGER REFERENCES raw_events (id),
    fecha_hora TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos >= 0),
    -- NULL solo cuando la moneda no se reconoció (la transacción queda pendiente).
    moneda TEXT CHECK (moneda IN ('CRC', 'USD')),
    tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso', 'transferencia', 'reembolsable')),
    cuenta_id INTEGER REFERENCES accounts (id),
    comercio_o_destinatario TEXT,
    descripcion TEXT,
    categoria_id INTEGER REFERENCES categories (id),
    estado TEXT NOT NULL DEFAULT 'confirmada'
        CHECK (estado IN ('confirmada', 'pendiente', 'ignorada')),
    -- NULL para transacciones manuales; con prefijo de fuente para las importadas.
    llave_unica TEXT UNIQUE,
    notas TEXT,
    creada_en TEXT NOT NULL,
    editada_en TEXT
);

CREATE INDEX idx_transactions_fecha ON transactions (fecha_hora);
CREATE INDEX idx_transactions_categoria ON transactions (categoria_id);

CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    campo TEXT NOT NULL CHECK (campo IN ('comercio', 'destinatario', 'descripcion')),
    patron TEXT NOT NULL,
    categoria_id INTEGER REFERENCES categories (id),
    tipo_forzado TEXT CHECK (tipo_forzado IN ('gasto', 'ingreso', 'transferencia', 'reembolsable')),
    prioridad INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE recurring_incomes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos >= 0),
    moneda TEXT NOT NULL DEFAULT 'CRC' CHECK (moneda IN ('CRC', 'USD')),
    dia_del_mes INTEGER NOT NULL CHECK (dia_del_mes BETWEEN 1 AND 31),
    cuenta_id INTEGER REFERENCES accounts (id),
    activa INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1))
);

CREATE TABLE budgets (
    categoria_id INTEGER PRIMARY KEY REFERENCES categories (id),
    monto_mensual_centimos INTEGER NOT NULL CHECK (monto_mensual_centimos >= 0),
    moneda TEXT NOT NULL DEFAULT 'CRC' CHECK (moneda IN ('CRC', 'USD'))
);

CREATE TABLE import_runs (
    id INTEGER PRIMARY KEY,
    fuente TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT,
    nuevos INTEGER NOT NULL DEFAULT 0,
    duplicados INTEGER NOT NULL DEFAULT 0,
    errores INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE settings (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
