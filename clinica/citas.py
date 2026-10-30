"""Agenda de citas presenciales y teleconsultas."""

import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   url_for)

from .auth import login_requerido
from .catalogos import ESTADOS_CITA, ESTADOS_LIBERAN_HORARIO
from .db import get_db
from .pacientes import (actualizar_paciente, buscar_por_dui, insertar_paciente, obtener_paciente)
from .validadores import leer_cita, leer_paciente

bp = Blueprint('citas', __name__, url_prefix='/citas')


def medicos_activos():
    return get_db().execute(
        "SELECT * FROM usuarios WHERE rol = 'medico' AND activo = 1 ORDER BY especialidad, nombre"
    ).fetchall()


def obtener_cita(cita_id):
    cita = get_db().execute(
        '''SELECT c.*, p.nombre AS paciente, p.celular, p.correo, p.dui,
                  u.nombre AS medico, e.token AS encuesta_token, e.respondida_en
           FROM citas c
           JOIN pacientes p ON p.id = c.paciente_id
           LEFT JOIN usuarios u ON u.id = c.medico_id
           LEFT JOIN encuestas e ON e.cita_id = c.id
           WHERE c.id = ?''',
        (cita_id,),
    ).fetchone()
    if cita is None:
        abort(404)
    return cita


def conflicto_horario(medico_id, fecha_hora, duracion_min, excluir_id=None):
    """Devuelve la cita del médico que se traslapa con el horario indicado, si existe."""
    if not medico_id:
        return None
    inicio = datetime.fromisoformat(fecha_hora)
    fin = inicio + timedelta(minutes=duracion_min)
    marcadores = ', '.join('?' for _ in ESTADOS_LIBERAN_HORARIO)
    candidatas = get_db().execute(
        f'''SELECT id, fecha_hora, duracion_min FROM citas
            WHERE medico_id = ? AND substr(fecha_hora, 1, 10) = ? AND id != ?
              AND estado NOT IN ({marcadores})''',
        (medico_id, fecha_hora[:10], excluir_id or 0, *ESTADOS_LIBERAN_HORARIO),
    ).fetchall()
    for c in candidatas:
        c_inicio = datetime.fromisoformat(c['fecha_hora'])
        if c_inicio < fin and inicio < c_inicio + timedelta(minutes=c['duracion_min']):
            return c
    return None


def nuevo_enlace_teleconsulta():
    base = current_app.config['TELECONSULTA_BASE_URL'].rstrip('/')
    return f'{base}/Teleconsulta-{secrets.token_hex(8)}'


def asegurar_encuesta(cita_id):
    """Crea (una sola vez) la encuesta de satisfacción de una cita atendida."""
    get_db().execute('INSERT OR IGNORE INTO encuestas (cita_id, token) VALUES (?, ?)',
                     (cita_id, secrets.token_urlsafe(16)))


def enlace_whatsapp(celular, mensaje):
    numero = '503' + (celular or '').replace('-', '')
    return f'https://wa.me/{numero}?text={quote(mensaje)}'


def _validar_medico(datos, errores):
    if not datos['medico_id']:
        return
    medico = get_db().execute(
        "SELECT * FROM usuarios WHERE id = ? AND rol = 'medico' AND activo = 1",
        (datos['medico_id'],),
    ).fetchone()
    if medico is None:
        errores.append('Médico no válido.')
    elif medico['especialidad'] != datos['especialidad']:
        errores.append(f'{medico["nombre"]} no atiende {datos["especialidad"]}.')
    elif datos['fecha_hora']:
        choque = conflicto_horario(datos['medico_id'], datos['fecha_hora'], datos['duracion_min'],
                                   datos.get('id'))
        if choque:
            errores.append(f'{medico["nombre"]} ya tiene una cita a las {choque["fecha_hora"][11:16]} '
                           'que se traslapa con ese horario.')


@bp.route('/')
@login_requerido
def lista():
    fecha = request.args.get('fecha') or date.today().isoformat()
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        dia = date.today()
    filtros = ['substr(c.fecha_hora, 1, 10) = ?']
    params = [dia.isoformat()]
    if 'medico_id' in request.args:
        medico_id = request.args.get('medico_id')
    else:
        medico_id = str(g.user['id']) if g.user['rol'] == 'medico' else ''
    if medico_id:
        filtros.append('c.medico_id = ?')
        params.append(medico_id)
    especialidad = request.args.get('especialidad') or ''
    if especialidad:
        filtros.append('c.especialidad = ?')
        params.append(especialidad)
    estado = request.args.get('estado') or ''
    if estado:
        filtros.append('c.estado = ?')
        params.append(estado)
    citas = get_db().execute(
        f'''SELECT c.*, p.nombre AS paciente, p.celular, u.nombre AS medico
            FROM citas c JOIN pacientes p ON p.id = c.paciente_id
            LEFT JOIN usuarios u ON u.id = c.medico_id
            WHERE {' AND '.join(filtros)} ORDER BY c.fecha_hora''',
        params,
    ).fetchall()
    return render_template('citas/lista.html', citas=citas, dia=dia, medicos=medicos_activos(),
                           medico_id=medico_id, especialidad=especialidad, estado=estado,
                           anterior=(dia - timedelta(days=1)).isoformat(),
                           siguiente=(dia + timedelta(days=1)).isoformat())


@bp.route('/nueva', methods=('GET', 'POST'))
@login_requerido
def nueva():
    paciente = None
    if request.values.get('paciente_id'):
        paciente = obtener_paciente(request.values.get('paciente_id', type=int))

    if request.method == 'POST':
        cita, errores = leer_cita(request.form)
        datos_paciente = None
        if paciente is None:
            datos_paciente, errores_paciente = leer_paciente(request.form)
            errores = errores_paciente + errores
        _validar_medico(cita, errores)
        if cita['fecha_hora'] and cita['fecha_hora'] < datetime.now().strftime('%Y-%m-%dT%H:%M'):
            errores.append('La fecha y hora de la cita ya pasaron.')

        if not errores:
            db = get_db()
            if paciente is None:
                if cita['usa_seguro']:
                    datos_paciente['aseguradora'] = cita['aseguradora']
                    datos_paciente['poliza'] = cita['poliza']
                existente = buscar_por_dui(datos_paciente['dui'])
                if existente:
                    # Paciente ya registrado: se reutiliza su expediente y se
                    # actualizan solo los datos de contacto y de seguro.
                    actualizados = dict(existente)
                    for campo in ('celular', 'correo', 'aseguradora', 'poliza'):
                        if datos_paciente.get(campo):
                            actualizados[campo] = datos_paciente[campo]
                    actualizar_paciente(existente['id'], actualizados)
                    paciente_id = existente['id']
                    flash(f'El DUI ya tenía expediente ({existente["nombre"]}); la cita se agregó a ese '
                          'expediente.', 'aviso')
                else:
                    paciente_id = insertar_paciente(datos_paciente)
            else:
                paciente_id = paciente['id']

            enlace = nuevo_enlace_teleconsulta() if cita['modalidad'] == 'teleconsulta' else None
            cur = db.execute(
                '''INSERT INTO citas (paciente_id, medico_id, especialidad, fecha_hora, duracion_min,
                       modalidad, motivo, enlace_teleconsulta, usa_seguro, aseguradora, poliza,
                       tiene_referencia, centro_referencia, medico_referente, motivo_referencia,
                       creado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (paciente_id, cita['medico_id'], cita['especialidad'], cita['fecha_hora'],
                 cita['duracion_min'], cita['modalidad'], cita['motivo'], enlace, cita['usa_seguro'],
                 cita['aseguradora'], cita['poliza'], cita['tiene_referencia'],
                 cita['centro_referencia'], cita['medico_referente'], cita['motivo_referencia'],
                 g.user['id']),
            )
            cita_id = cur.lastrowid

            from .historial import guardar_documentos
            guardados, errores_doc = guardar_documentos(
                paciente_id, request.files.getlist('documentos'),
                request.form.get('categoria_documento') or 'Hoja de referencia',
                request.form.get('descripcion_documento'))
            db.commit()
            for e in errores_doc:
                flash(e, 'error')
            flash('Cita agendada.' + (f' Se adjuntaron {guardados} documento(s).' if guardados else ''),
                  'ok')
            return redirect(url_for('citas.ver', cita_id=cita_id))
        for e in errores:
            flash(e, 'error')

    form = request.form
    if request.method == 'GET':
        form = {'fecha': request.args.get('fecha', date.today().isoformat()), 'duracion_min': 30,
                'especialidad': request.args.get('especialidad', '')}
    return render_template('citas/form.html', paciente=paciente, cita=None, form=form,
                           medicos=medicos_activos())


@bp.route('/<int:cita_id>')
@login_requerido
def ver(cita_id):
    cita = obtener_cita(cita_id)
    clinica = current_app.config['NOMBRE_CLINICA']
    whatsapp_cita = enlace_whatsapp(
        cita['celular'],
        f'Hola {cita["paciente"]}, le recordamos su cita de {cita["especialidad"]} en {clinica} '
        f'el {datetime.fromisoformat(cita["fecha_hora"]).strftime("%d/%m/%Y a las %H:%M")}.'
        + (f' Ingrese a su teleconsulta aquí: {cita["enlace_teleconsulta"]}'
           if cita['enlace_teleconsulta'] else ''),
    )
    enlace_encuesta = whatsapp_encuesta = None
    if cita['encuesta_token']:
        enlace_encuesta = url_for('encuestas.responder', token=cita['encuesta_token'], _external=True)
        whatsapp_encuesta = enlace_whatsapp(
            cita['celular'],
            f'Gracias por visitarnos en {clinica}. Nos ayudaría mucho conocer su opinión sobre la '
            f'atención recibida: {enlace_encuesta}',
        )
    consulta = get_db().execute('SELECT id FROM consultas WHERE cita_id = ?', (cita_id,)).fetchone()
    return render_template('citas/ver.html', cita=cita, whatsapp_cita=whatsapp_cita,
                           enlace_encuesta=enlace_encuesta, whatsapp_encuesta=whatsapp_encuesta,
                           consulta=consulta)


@bp.route('/<int:cita_id>/editar', methods=('GET', 'POST'))
@login_requerido
def editar(cita_id):
    actual = obtener_cita(cita_id)
    if actual['estado'] in ('atendida', 'cancelada'):
        flash('No se puede modificar una cita atendida o cancelada.', 'error')
        return redirect(url_for('citas.ver', cita_id=cita_id))
    if request.method == 'POST':
        cita, errores = leer_cita(request.form)
        cita['id'] = cita_id
        _validar_medico(cita, errores)
        if not errores:
            enlace = actual['enlace_teleconsulta']
            if cita['modalidad'] == 'teleconsulta' and not enlace:
                enlace = nuevo_enlace_teleconsulta()
            elif cita['modalidad'] == 'presencial':
                enlace = None
            db = get_db()
            db.execute(
                '''UPDATE citas SET medico_id = ?, especialidad = ?, fecha_hora = ?, duracion_min = ?,
                       modalidad = ?, motivo = ?, enlace_teleconsulta = ?, usa_seguro = ?,
                       aseguradora = ?, poliza = ?, tiene_referencia = ?, centro_referencia = ?,
                       medico_referente = ?, motivo_referencia = ?
                   WHERE id = ?''',
                (cita['medico_id'], cita['especialidad'], cita['fecha_hora'], cita['duracion_min'],
                 cita['modalidad'], cita['motivo'], enlace, cita['usa_seguro'], cita['aseguradora'],
                 cita['poliza'], cita['tiene_referencia'], cita['centro_referencia'],
                 cita['medico_referente'], cita['motivo_referencia'], cita_id),
            )
            db.commit()
            flash('Cita actualizada.', 'ok')
            return redirect(url_for('citas.ver', cita_id=cita_id))
        for e in errores:
            flash(e, 'error')
        form = request.form
    else:
        form = dict(actual)
        form['fecha'], form['hora'] = actual['fecha_hora'].split('T')
        form['cita_aseguradora'] = actual['aseguradora']
        form['cita_poliza'] = actual['poliza']
    paciente = obtener_paciente(actual['paciente_id'])
    return render_template('citas/form.html', paciente=paciente, cita=actual, form=form,
                           medicos=medicos_activos())


@bp.route('/<int:cita_id>/estado', methods=('POST',))
@login_requerido
def cambiar_estado(cita_id):
    cita = obtener_cita(cita_id)
    estado = request.form.get('estado')
    if estado not in ESTADOS_CITA:
        abort(400)
    if cita['estado'] == 'atendida' and g.user['rol'] != 'admin':
        flash('Solo un administrador puede cambiar el estado de una cita atendida.', 'error')
        return redirect(url_for('citas.ver', cita_id=cita_id))
    db = get_db()
    db.execute('UPDATE citas SET estado = ? WHERE id = ?', (estado, cita_id))
    if estado == 'atendida':
        asegurar_encuesta(cita_id)
    db.commit()
    flash(f'Cita marcada como {ESTADOS_CITA[estado].lower()}.', 'ok')
    volver = request.form.get('volver', '')
    if not volver.startswith('/') or volver.startswith('//'):
        volver = url_for('citas.ver', cita_id=cita_id)
    return redirect(volver)
