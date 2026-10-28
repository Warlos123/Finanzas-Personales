-- Etapa 5: estados de cuenta del BCR para reconciliar. Se guarda el texto que sale de
-- `pdftotext` (no el PDF); los movimientos se vuelven a leer de ese texto cada vez.

CREATE TABLE bank_statements (
    id INTEGER PRIMARY KEY,
    hash TEXT NOT NULL UNIQUE,
    texto TEXT NOT NULL,
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
