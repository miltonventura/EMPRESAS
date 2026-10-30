"""Catálogos de valores usados en formularios, validaciones y reportes."""

ESPECIALIDADES = ['Medicina General', 'Otorrinolaringología', 'Ginecología']

MEDIOS_ENTERADO = [
    'Recomendación de familiar o amigo',
    'Facebook / Instagram',
    'TikTok',
    'Google / búsqueda en internet',
    'WhatsApp',
    'Referencia de otro médico o centro',
    'Aseguradora',
    'Radio / televisión / prensa',
    'Rótulo o pasó por la clínica',
    'Ya era paciente',
    'Otro',
]

ROLES = {
    'admin': 'Administrador',
    'medico': 'Médico',
    'recepcion': 'Recepción',
}

MODALIDADES = {
    'presencial': 'Presencial',
    'teleconsulta': 'Teleconsulta',
}

ESTADOS_CITA = {
    'programada': 'Programada',
    'confirmada': 'Confirmada',
    'atendida': 'Atendida',
    'cancelada': 'Cancelada',
    'no_asistio': 'No asistió',
}

# Estados que ya no ocupan el horario del médico.
ESTADOS_LIBERAN_HORARIO = ('cancelada', 'no_asistio')

CATEGORIAS_DOCUMENTO = [
    'Examen de laboratorio',
    'Imagen / radiografía / ultrasonografía',
    'Audiometría / estudio ORL',
    'Citología / estudio ginecológico',
    'Hoja de referencia',
    'Receta',
    'Constancia / incapacidad',
    'Documento de seguro',
    'Otro',
]

EXTENSIONES_PERMITIDAS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic',
    'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv', 'dcm',
}

# Preguntas de la encuesta de satisfacción (escala 1 a 5).
# Las marcadas como opcionales admiten "No aplica" (p. ej. en teleconsultas).
PREGUNTAS_ENCUESTA = [
    ('calif_medico', 'Atención recibida del médico', False),
    ('calif_recepcion', 'Atención del personal de recepción', False),
    ('calif_enfermeria', 'Atención del personal de enfermería', True),
    ('calif_puntualidad', 'Puntualidad y tiempo de espera', False),
    ('calif_instalaciones', 'Instalaciones / calidad de la videollamada', True),
    ('calif_general', 'Satisfacción general con el servicio', False),
]

ESCALA = {
    1: 'Muy insatisfecho',
    2: 'Insatisfecho',
    3: 'Neutral',
    4: 'Satisfecho',
    5: 'Muy satisfecho',
}

ETIQUETAS_CORTAS = {
    'calif_medico': 'Médico',
    'calif_recepcion': 'Recepción',
    'calif_enfermeria': 'Enfermería',
    'calif_puntualidad': 'Puntualidad',
    'calif_instalaciones': 'Instalaciones',
    'calif_general': 'General',
}
