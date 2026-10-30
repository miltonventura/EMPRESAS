"""Historial clínico: notas de consulta y documentos o exámenes adjuntos."""

import mimetypes
import os
import secrets
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)

from .auth import login_requerido, roles_requeridos
from .catalogos import CATEGORIAS_DOCUMENTO, ESPECIALIDADES, EXTENSIONES_PERMITIDAS
from .citas import asegurar_encuesta
from .db import get_db
from .pacientes import obtener_paciente
from .validadores import texto

bp = Blueprint('historial', __name__, url_prefix='/historial')

CAMPOS_CONSULTA = ('motivo', 'presion_arterial', 'frecuencia_cardiaca', 'temperatura', 'peso_kg',
                   'talla_cm', 'examen_fisico', 'diagnostico', 'tratamiento', 'indicaciones')

# Tipos que el navegador puede mostrar directamente; el resto se descarga.
TIPOS_EN_LINEA = {'application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp',
                  'text/plain'}


def _extension(nombre):
    return nombre.rsplit('.', 1)[1].lower() if '.' in nombre else ''


def guardar_documentos(paciente_id, archivos, categoria, descripcion=None, consulta_id=None):
    """Guarda los archivos subidos en el expediente. No hace commit.

    Devuelve (cantidad_guardada, errores).
    """
    archivos = [a for a in archivos if a and a.filename]
    if not archivos:
        return 0, []
    if categoria not in CATEGORIAS_DOCUMENTO:
        return 0, ['Seleccione una categoría válida para el documento.']
    errores = []
    guardados = 0
    carpeta = os.path.join(current_app.config['UPLOAD_FOLDER'], str(paciente_id))
    os.makedirs(carpeta, exist_ok=True)
    for archivo in archivos:
        nombre_original = os.path.basename(archivo.filename.replace('\\', '/'))
        ext = _extension(nombre_original)
        if ext not in EXTENSIONES_PERMITIDAS:
            errores.append(f'"{nombre_original}": tipo de archivo no permitido.')
            continue
        nombre_archivo = f'{paciente_id}/{secrets.token_hex(16)}.{ext}'
        ruta = os.path.join(current_app.config['UPLOAD_FOLDER'], nombre_archivo)
        archivo.save(ruta)
        tamano = os.path.getsize(ruta)
        if tamano == 0:
            os.remove(ruta)
            errores.append(f'"{nombre_original}" está vacío.')
            continue
        get_db().execute(
            '''INSERT INTO documentos (paciente_id, consulta_id, categoria, descripcion,
                   nombre_original, nombre_archivo, tipo_mime, tamano, subido_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (paciente_id, consulta_id, categoria, (descripcion or '').strip() or None,
             nombre_original, nombre_archivo, mimetypes.guess_type(nombre_original)[0],
             tamano, g.user['id']),
        )
        guardados += 1
    return guardados, errores


@bp.route('/paciente/<int:paciente_id>/consulta/nueva', methods=('GET', 'POST'))
@roles_requeridos('admin', 'medico')
def consulta_nueva(paciente_id):
    paciente = obtener_paciente(paciente_id)
    db = get_db()
    cita = None
    cita_id = request.values.get('cita_id', type=int)
    if cita_id:
        cita = db.execute('SELECT * FROM citas WHERE id = ? AND paciente_id = ?',
                          (cita_id, paciente_id)).fetchone()
        if cita is None:
            abort(404)
        existente = db.execute('SELECT id FROM consultas WHERE cita_id = ?', (cita_id,)).fetchone()
        if existente:
            return redirect(url_for('historial.consulta_ver', consulta_id=existente['id']))

    if request.method == 'POST':
        datos = {c: texto(request.form, c) for c in CAMPOS_CONSULTA}
        especialidad = request.form.get('especialidad')
        errores = []
        if not datos['motivo']:
            errores.append('El motivo de consulta es obligatorio.')
        if especialidad not in ESPECIALIDADES:
            errores.append('Seleccione la especialidad.')
        if not errores:
            fecha = cita['fecha_hora'] if cita else datetime.now().strftime('%Y-%m-%dT%H:%M')
            cur = db.execute(
                f'''INSERT INTO consultas (paciente_id, cita_id, medico_id, especialidad, fecha,
                        {", ".join(CAMPOS_CONSULTA)})
                    VALUES (?, ?, ?, ?, ?, {", ".join("?" for _ in CAMPOS_CONSULTA)})''',
                (paciente_id, cita_id, g.user['id'], especialidad, fecha,
                 *[datos[c] for c in CAMPOS_CONSULTA]),
            )
            consulta_id = cur.lastrowid
            if cita:
                db.execute("UPDATE citas SET estado = 'atendida' WHERE id = ?", (cita_id,))
                asegurar_encuesta(cita_id)
            guardados, errores_doc = guardar_documentos(
                paciente_id, request.files.getlist('documentos'),
                request.form.get('categoria_documento') or 'Otro',
                request.form.get('descripcion_documento'), consulta_id)
            db.commit()
            for e in errores_doc:
                flash(e, 'error')
            flash('Consulta registrada en el historial.', 'ok')
            return redirect(url_for('historial.consulta_ver', consulta_id=consulta_id))
        for e in errores:
            flash(e, 'error')
        form = request.form
    else:
        form = {'motivo': cita['motivo'] if cita else '',
                'especialidad': (cita['especialidad'] if cita else g.user['especialidad']) or ''}
    return render_template('historial/consulta_form.html', paciente=paciente, cita=cita, form=form)


@bp.route('/consulta/<int:consulta_id>')
@roles_requeridos('admin', 'medico')
def consulta_ver(consulta_id):
    db = get_db()
    consulta = db.execute(
        '''SELECT k.*, u.nombre AS medico FROM consultas k JOIN usuarios u ON u.id = k.medico_id
           WHERE k.id = ?''',
        (consulta_id,),
    ).fetchone()
    if consulta is None:
        abort(404)
    paciente = obtener_paciente(consulta['paciente_id'])
    documentos = db.execute('SELECT * FROM documentos WHERE consulta_id = ? ORDER BY creado',
                            (consulta_id,)).fetchall()
    return render_template('historial/consulta_ver.html', consulta=consulta, paciente=paciente,
                           documentos=documentos)


@bp.route('/paciente/<int:paciente_id>/documentos', methods=('POST',))
@login_requerido
def documentos_subir(paciente_id):
    obtener_paciente(paciente_id)
    archivos = request.files.getlist('documentos')
    guardados, errores = guardar_documentos(paciente_id, archivos, request.form.get('categoria'),
                                            request.form.get('descripcion'))
    get_db().commit()
    if not any(a.filename for a in archivos):
        errores.append('Seleccione al menos un archivo.')
    for e in errores:
        flash(e, 'error')
    if guardados:
        flash(f'Se adjuntaron {guardados} documento(s) al expediente.', 'ok')
    return redirect(url_for('pacientes.ver', paciente_id=paciente_id) + '#documentos')


def _obtener_documento(documento_id):
    doc = get_db().execute('SELECT * FROM documentos WHERE id = ?', (documento_id,)).fetchone()
    if doc is None:
        abort(404)
    return doc


@bp.route('/documento/<int:documento_id>')
@login_requerido
def documento_ver(documento_id):
    doc = _obtener_documento(documento_id)
    tipo = doc['tipo_mime'] or 'application/octet-stream'
    respuesta = send_from_directory(
        current_app.config['UPLOAD_FOLDER'], doc['nombre_archivo'], mimetype=tipo,
        as_attachment=tipo not in TIPOS_EN_LINEA or request.args.get('descargar') == '1',
        download_name=doc['nombre_original'],
    )
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    respuesta.headers['Cache-Control'] = 'private, no-store'
    return respuesta


@bp.route('/documento/<int:documento_id>/eliminar', methods=('POST',))
@roles_requeridos('admin', 'medico')
def documento_eliminar(documento_id):
    doc = _obtener_documento(documento_id)
    db = get_db()
    db.execute('DELETE FROM documentos WHERE id = ?', (documento_id,))
    db.commit()
    ruta = os.path.join(current_app.config['UPLOAD_FOLDER'], doc['nombre_archivo'])
    if os.path.exists(ruta):
        os.remove(ruta)
    flash(f'Documento "{doc["nombre_original"]}" eliminado.', 'ok')
    return redirect(url_for('pacientes.ver', paciente_id=doc['paciente_id']) + '#documentos')
