-- Esquema de la base de datos de la clínica (SQLite).
-- Las fechas se guardan como texto ISO 8601 en hora local: 'AAAA-MM-DDTHH:MM'.

CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario       TEXT    NOT NULL UNIQUE,
    nombre        TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    rol           TEXT    NOT NULL CHECK (rol IN ('admin', 'medico', 'recepcion')),
    especialidad  TEXT,
    activo        INTEGER NOT NULL DEFAULT 1,
    creado        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);

-- Expediente: un registro por paciente atendido.
CREATE TABLE IF NOT EXISTS pacientes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre               TEXT    NOT NULL,
    dui                  TEXT    UNIQUE,          -- NULL para menores de edad sin DUI
    responsable_nombre   TEXT,                    -- obligatorio si no hay DUI
    responsable_dui      TEXT,
    fecha_nacimiento     TEXT,
    sexo                 TEXT,
    celular              TEXT    NOT NULL,
    correo               TEXT,
    direccion            TEXT,
    aseguradora          TEXT,                    -- seguro médico habitual
    poliza               TEXT,
    medio_enterado       TEXT    NOT NULL,        -- cómo se enteró de la clínica
    medio_detalle        TEXT,
    alergias             TEXT,
    antecedentes         TEXT,
    creado               TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')),
    actualizado          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_pacientes_nombre ON pacientes (nombre);

CREATE TABLE IF NOT EXISTS citas (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id          INTEGER NOT NULL REFERENCES pacientes (id) ON DELETE CASCADE,
    medico_id            INTEGER REFERENCES usuarios (id),
    especialidad         TEXT    NOT NULL,
    fecha_hora           TEXT    NOT NULL,
    duracion_min         INTEGER NOT NULL DEFAULT 30,
    modalidad            TEXT    NOT NULL CHECK (modalidad IN ('presencial', 'teleconsulta')),
    motivo               TEXT,
    estado               TEXT    NOT NULL DEFAULT 'programada'
                         CHECK (estado IN ('programada', 'confirmada', 'atendida', 'cancelada', 'no_asistio')),
    enlace_teleconsulta  TEXT,
    usa_seguro           INTEGER NOT NULL DEFAULT 0,
    aseguradora          TEXT,
    poliza               TEXT,
    tiene_referencia     INTEGER NOT NULL DEFAULT 0,
    centro_referencia    TEXT,
    medico_referente     TEXT,
    motivo_referencia    TEXT,
    creado_por           INTEGER REFERENCES usuarios (id),
    creado               TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_citas_fecha ON citas (fecha_hora);
CREATE INDEX IF NOT EXISTS idx_citas_paciente ON citas (paciente_id);

-- Notas clínicas del historial.
CREATE TABLE IF NOT EXISTS consultas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id      INTEGER NOT NULL REFERENCES pacientes (id) ON DELETE CASCADE,
    cita_id          INTEGER REFERENCES citas (id) ON DELETE SET NULL,
    medico_id        INTEGER NOT NULL REFERENCES usuarios (id),
    especialidad     TEXT    NOT NULL,
    fecha            TEXT    NOT NULL,
    motivo           TEXT    NOT NULL,
    presion_arterial TEXT,
    frecuencia_cardiaca TEXT,
    temperatura      TEXT,
    peso_kg          TEXT,
    talla_cm         TEXT,
    examen_fisico    TEXT,
    diagnostico      TEXT,
    tratamiento      TEXT,
    indicaciones     TEXT,
    creado           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_consultas_paciente ON consultas (paciente_id);

-- Documentos y exámenes adjuntos al historial.
CREATE TABLE IF NOT EXISTS documentos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id      INTEGER NOT NULL REFERENCES pacientes (id) ON DELETE CASCADE,
    consulta_id      INTEGER REFERENCES consultas (id) ON DELETE SET NULL,
    categoria        TEXT    NOT NULL,
    descripcion      TEXT,
    nombre_original  TEXT    NOT NULL,
    nombre_archivo   TEXT    NOT NULL UNIQUE,
    tipo_mime        TEXT,
    tamano           INTEGER NOT NULL,
    subido_por       INTEGER REFERENCES usuarios (id),
    creado           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_documentos_paciente ON documentos (paciente_id);

-- Encuestas de experiencia del paciente (una por cita atendida).
CREATE TABLE IF NOT EXISTS encuestas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id             INTEGER NOT NULL UNIQUE REFERENCES citas (id) ON DELETE CASCADE,
    token               TEXT    NOT NULL UNIQUE,
    creado              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')),
    respondida_en       TEXT,
    calif_medico        INTEGER CHECK (calif_medico BETWEEN 1 AND 5),
    calif_recepcion     INTEGER CHECK (calif_recepcion BETWEEN 1 AND 5),
    calif_enfermeria    INTEGER CHECK (calif_enfermeria BETWEEN 1 AND 5),
    calif_puntualidad   INTEGER CHECK (calif_puntualidad BETWEEN 1 AND 5),
    calif_instalaciones INTEGER CHECK (calif_instalaciones BETWEEN 1 AND 5),
    calif_general       INTEGER CHECK (calif_general BETWEEN 1 AND 5),
    nps                 INTEGER CHECK (nps BETWEEN 0 AND 10),
    comentarios         TEXT
);
