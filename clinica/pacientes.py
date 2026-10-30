"""Expedientes de pacientes."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import login_requerido, puede_ver_clinico
from .db import get_db
from .validadores import leer_paciente

bp = Blueprint('pacientes', __name__, url_prefix='/pacientes')

CAMPOS = ('nombre', 'dui', 'responsable_nombre', 'responsable_dui', 'fecha_nacimiento', 'sexo',
          'celular', 'correo', 'direccion', 'aseguradora', 'poliza', 'medio_enterado',
          'medio_detalle', 'alergias', 'antecedentes')


def obtener_paciente(paciente_id):
    paciente = get_db().execute('SELECT * FROM pacientes WHERE id = ?', (paciente_id,)).fetchone()
    if paciente is None:
        abort(404)
    return paciente


def buscar_por_dui(dui):
    if not dui:
        return None
    return get_db().execute('SELECT * FROM pacientes WHERE dui = ?', (dui,)).fetchone()


def insertar_paciente(datos):
    cur = get_db().execute(
        f'INSERT INTO pacientes ({", ".join(CAMPOS)}) VALUES ({", ".join("?" for _ in CAMPOS)})',
        [datos.get(c) for c in CAMPOS],
    )
    return cur.lastrowid


def actualizar_paciente(paciente_id, datos):
    asignaciones = ', '.join(f'{c} = ?' for c in CAMPOS)
    get_db().execute(
        f"UPDATE pacientes SET {asignaciones}, actualizado = strftime('%Y-%m-%dT%H:%M', 'now', 'localtime') "
        'WHERE id = ?',
        [datos.get(c) for c in CAMPOS] + [paciente_id],
    )


@bp.route('/')
@login_requerido
def lista():
    q = (request.args.get('q') or '').strip()
    db = get_db()
    consulta = '''
        SELECT p.*, (SELECT MAX(fecha_hora) FROM citas c
                     WHERE c.paciente_id = p.id AND c.estado = 'atendida') AS ultima_visita
        FROM pacientes p'''
    if q:
        patron = f'%{q}%'
        digitos = ''.join(ch for ch in q if ch.isdigit())
        filas = db.execute(
            consulta + ' WHERE p.nombre LIKE ? OR p.dui LIKE ? OR p.responsable_dui LIKE ? '
                       "OR REPLACE(p.celular, '-', '') LIKE ? ORDER BY p.nombre LIMIT 200",
            (patron, patron, patron, f'%{digitos}%' if digitos else patron),
        ).fetchall()
    else:
        filas = db.execute(consulta + ' ORDER BY p.creado DESC LIMIT 50').fetchall()
    return render_template('pacientes/lista.html', pacientes=filas, q=q)


@bp.route('/nuevo', methods=('GET', 'POST'))
@login_requerido
def nuevo():
    if request.method == 'POST':
        datos, errores = leer_paciente(request.form)
        if not errores and buscar_por_dui(datos['dui']):
            errores.append('Ya existe un expediente con ese DUI.')
        if not errores:
            paciente_id = insertar_paciente(datos)
            get_db().commit()
            flash('Expediente creado.', 'ok')
            return redirect(url_for('pacientes.ver', paciente_id=paciente_id))
        for e in errores:
            flash(e, 'error')
    return render_template('pacientes/form.html', paciente=None, form=request.form)


@bp.route('/<int:paciente_id>/editar', methods=('GET', 'POST'))
@login_requerido
def editar(paciente_id):
    paciente = obtener_paciente(paciente_id)
    if request.method == 'POST':
        datos, errores = leer_paciente(request.form)
        if not errores:
            otro = buscar_por_dui(datos['dui'])
            if otro and otro['id'] != paciente_id:
                errores.append('Ya existe otro expediente con ese DUI.')
        if not errores:
            actualizar_paciente(paciente_id, datos)
            get_db().commit()
            flash('Expediente actualizado.', 'ok')
            return redirect(url_for('pacientes.ver', paciente_id=paciente_id))
        for e in errores:
            flash(e, 'error')
    return render_template('pacientes/form.html', paciente=paciente,
                           form=request.form if request.method == 'POST' else dict(paciente))


@bp.route('/<int:paciente_id>')
@login_requerido
def ver(paciente_id):
    paciente = obtener_paciente(paciente_id)
    db = get_db()
    citas = db.execute(
        '''SELECT c.*, u.nombre AS medico, e.token AS encuesta_token, e.respondida_en,
                  e.calif_general
           FROM citas c
           LEFT JOIN usuarios u ON u.id = c.medico_id
           LEFT JOIN encuestas e ON e.cita_id = c.id
           WHERE c.paciente_id = ? ORDER BY c.fecha_hora DESC''',
        (paciente_id,),
    ).fetchall()
    consultas = []
    if puede_ver_clinico():
        consultas = db.execute(
            '''SELECT k.*, u.nombre AS medico FROM consultas k
               JOIN usuarios u ON u.id = k.medico_id
               WHERE k.paciente_id = ? ORDER BY k.fecha DESC''',
            (paciente_id,),
        ).fetchall()
    documentos = db.execute(
        '''SELECT d.*, u.nombre AS subido_por_nombre FROM documentos d
           LEFT JOIN usuarios u ON u.id = d.subido_por
           WHERE d.paciente_id = ? ORDER BY d.creado DESC''',
        (paciente_id,),
    ).fetchall()
    referencias = [c for c in citas if c['tiene_referencia']]
    return render_template('pacientes/ver.html', paciente=paciente, citas=citas,
                           consultas=consultas, documentos=documentos, referencias=referencias)

