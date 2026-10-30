"""Normalización y validación de los datos que se capturan en formularios."""

import re
from datetime import datetime

from .catalogos import ESPECIALIDADES, MEDIOS_ENTERADO, MODALIDADES

_RE_CORREO = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def texto(form, campo):
    """Devuelve el valor del campo sin espacios extremos, o None si está vacío."""
    valor = (form.get(campo) or '').strip()
    return valor or None


def casilla(form, campo):
    return 1 if form.get(campo) in ('1', 'on', 'si', 'true') else 0


def normalizar_dui(valor):
    """Acepta '123456789' o '12345678-9' y devuelve '12345678-9'; None si no es válido."""
    digitos = re.sub(r'[\s-]', '', valor or '')
    if not re.fullmatch(r'\d{9}', digitos):
        return None
    return f'{digitos[:8]}-{digitos[8]}'


def normalizar_celular(valor):
    """Acepta 8 dígitos con o sin prefijo +503 y devuelve '7123-4567'; None si no es válido."""
    digitos = re.sub(r'[\s\-()+]', '', valor or '')
    if len(digitos) == 11 and digitos.startswith('503'):
        digitos = digitos[3:]
    if not re.fullmatch(r'\d{8}', digitos):
        return None
    return f'{digitos[:4]}-{digitos[4:]}'


def correo_valido(valor):
    return bool(_RE_CORREO.match(valor or ''))


def fecha_valida(valor, formato='%Y-%m-%d'):
    try:
        datetime.strptime(valor, formato)
        return True
    except (TypeError, ValueError):
        return False


def leer_paciente(form):
    """Lee los datos del paciente de un formulario. Devuelve (datos, errores)."""
    errores = []
    datos = {
        'nombre': texto(form, 'nombre'),
        'fecha_nacimiento': texto(form, 'fecha_nacimiento'),
        'sexo': texto(form, 'sexo'),
        'correo': texto(form, 'correo'),
        'direccion': texto(form, 'direccion'),
        'aseguradora': texto(form, 'aseguradora'),
        'poliza': texto(form, 'poliza'),
        'medio_enterado': texto(form, 'medio_enterado'),
        'medio_detalle': texto(form, 'medio_detalle'),
        'responsable_nombre': texto(form, 'responsable_nombre'),
        'responsable_dui': None,
        'alergias': texto(form, 'alergias'),
        'antecedentes': texto(form, 'antecedentes'),
    }

    if not datos['nombre']:
        errores.append('El nombre completo del paciente es obligatorio.')

    dui = texto(form, 'dui')
    if dui:
        datos['dui'] = normalizar_dui(dui)
        if not datos['dui']:
            errores.append('El DUI debe tener 9 dígitos (formato 12345678-9).')
    else:
        # Menores de edad: se identifican con los datos de su responsable.
        datos['dui'] = None
        dui_resp = texto(form, 'responsable_dui')
        if not datos['responsable_nombre'] or not dui_resp:
            errores.append('Ingrese el DUI del paciente. Si es menor de edad, ingrese el nombre '
                           'y DUI de su responsable.')
        else:
            datos['responsable_dui'] = normalizar_dui(dui_resp)
            if not datos['responsable_dui']:
                errores.append('El DUI del responsable debe tener 9 dígitos (formato 12345678-9).')

    datos['celular'] = normalizar_celular(texto(form, 'celular'))
    if not datos['celular']:
        errores.append('El celular debe tener 8 dígitos (puede incluir +503).')

    if datos['correo'] and not correo_valido(datos['correo']):
        errores.append('El correo electrónico no es válido.')

    if datos['fecha_nacimiento'] and not fecha_valida(datos['fecha_nacimiento']):
        errores.append('La fecha de nacimiento no es válida.')

    if datos['medio_enterado'] not in MEDIOS_ENTERADO:
        errores.append('Indique por qué medio se enteró el paciente de la clínica.')
    elif datos['medio_enterado'] == 'Otro' and not datos['medio_detalle']:
        errores.append('Especifique por qué otro medio se enteró de la clínica.')

    return datos, errores


def leer_cita(form):
    """Lee los datos propios de la cita. Devuelve (datos, errores)."""
    errores = []
    fecha = texto(form, 'fecha')
    hora = texto(form, 'hora')
    datos = {
        'especialidad': texto(form, 'especialidad'),
        'medico_id': texto(form, 'medico_id'),
        'modalidad': texto(form, 'modalidad'),
        'motivo': texto(form, 'motivo'),
        'usa_seguro': casilla(form, 'usa_seguro'),
        'aseguradora': texto(form, 'cita_aseguradora'),
        'poliza': texto(form, 'cita_poliza'),
        'tiene_referencia': casilla(form, 'tiene_referencia'),
        'centro_referencia': texto(form, 'centro_referencia'),
        'medico_referente': texto(form, 'medico_referente'),
        'motivo_referencia': texto(form, 'motivo_referencia'),
    }

    if datos['especialidad'] not in ESPECIALIDADES:
        errores.append('Seleccione la especialidad.')
    if datos['modalidad'] not in MODALIDADES:
        errores.append('Seleccione la modalidad (presencial o teleconsulta).')

    if not fecha_valida(f'{fecha}T{hora}', '%Y-%m-%dT%H:%M'):
        errores.append('Indique una fecha y hora válidas para la cita.')
        datos['fecha_hora'] = None
    else:
        datos['fecha_hora'] = f'{fecha}T{hora}'

    try:
        datos['duracion_min'] = int(form.get('duracion_min') or 30)
        if not 5 <= datos['duracion_min'] <= 240:
            raise ValueError
    except ValueError:
        errores.append('La duración debe estar entre 5 y 240 minutos.')
        datos['duracion_min'] = 30

    if datos['medico_id']:
        try:
            datos['medico_id'] = int(datos['medico_id'])
        except ValueError:
            errores.append('Médico no válido.')
            datos['medico_id'] = None

    if datos['usa_seguro']:
        if not datos['aseguradora']:
            errores.append('Indique la aseguradora que utilizará el paciente.')
    else:
        datos['aseguradora'] = datos['poliza'] = None

    if datos['tiene_referencia']:
        if not datos['centro_referencia']:
            errores.append('Indique el centro médico que refiere al paciente.')
    else:
        datos['centro_referencia'] = datos['medico_referente'] = datos['motivo_referencia'] = None

    return datos, errores
