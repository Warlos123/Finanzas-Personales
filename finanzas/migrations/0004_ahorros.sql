-- Pestaña de ahorros (pedido del usuario): CDP e inversiones en el S&P 500. Por ahora todo a mano.

CREATE TABLE savings (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,  -- 'cdp' | 'sp500' (se valida en ahorros.py para poder sumar tipos sin migrar)
    nombre TEXT NOT NULL,
    moneda TEXT NOT NULL DEFAULT 'CRC' CHECK (moneda IN ('CRC', 'USD')),
    invertido_centimos INTEGER NOT NULL CHECK (invertido_centimos >= 0),
    valor_actual_centimos INTEGER NOT NULL CHECK (valor_actual_centimos >= 0),
    tasa_anual TEXT,  -- % anual, solo CDP (ej. '5.25')
    inicio TEXT,  -- AAAA-MM-DD
    vence TEXT,  -- AAAA-MM-DD, solo CDP
    notas TEXT,
    actualizado_en TEXT NOT NULL
);
