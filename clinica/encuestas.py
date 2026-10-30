"""Encuesta de experiencia del paciente (pública, se accede con un enlace único)."""

import csv
import io
from datetime import datetime

from flask import Blueprint, Response, abort, flash, render_template, request

from .auth import roles_requeridos
from .catalogos import PREGUNTAS_ENCUESTA
from .db import get_db
from .reportes import leer_periodo

bp = Blueprint('encuestas', __name__)


def _encuesta_por_token(token):
    encuesta = get_db().execute(
        '''SELECT e.*, c.especialidad, c.modalidad, c.fecha_hora, p.nombre AS paciente,
                  u.nombre AS medico
           FROM encuestas e JOIN citas c ON c.id = e.cita_id
           JOIN pacientes p ON p.id = c.paciente_id
           LEFT JOIN usuarios u ON u.id = c.medico_id
           WHERE e.token = ?''',
        (token,),
    ).fetchone()
    if encuesta is None:
        abort(404)
    return encuesta


@bp.route('/encuesta/<token>', methods=('GET', 'POST'))
def responder(token):
    encuesta = _encuesta_por_token(token)
    if encuesta['respondida_en']:
        return render_template('encuestas/gracias.html', encuesta=encuesta, ya_respondida=True)

    if request.method == 'POST':
        errores = []
        valores = {}
        for campo, etiqueta, opcional in PREGUNTAS_ENCUESTA:
            valor = request.form.get(campo, '')
            if valor in ('', 'na') and opcional:
                valores[campo] = None
            elif valor in ('1', '2', '3', '4', '5'):
                valores[campo] = int(valor)
            else:
                errores.append(f'Responda: {etiqueta}.')
        nps = request.form.get('nps', '')
        if nps.isdigit() and 0 <= int(nps) <= 10:
            valores['nps'] = int(nps)
        else:
            errores.append('Indique qué tan probable es que nos recomiende (0 a 10).')
        if not errores:
            db = get_db()
            columnas = list(valores)
            db.execute(
                f'''UPDATE encuestas SET {", ".join(f"{c} = ?" for c in columnas)},
                        comentarios = ?, respondida_en = ?
                    WHERE id = ? AND respondida_en IS NULL''',
                (*valores.values(), (request.form.get('comentarios') or '').strip()[:2000] or None,
                 datetime.now().strftime('%Y-%m-%dT%H:%M'), encuesta['id']),
            )
            db.commit()
            return render_template('encuestas/gracias.html', encuesta=encuesta, ya_respondida=False)
        for e in errores:
            flash(e, 'error')
    return render_template('encuestas/responder.html', encuesta=encuesta, form=request.form)


def _celda(valor):
    """Evita que Excel interprete como fórmula un texto escrito por el paciente."""
    if isinstance(valor, str) and valor[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + valor
    return '' if valor is None else valor


def _respuestas(desde, hasta):
    return get_db().execute(
        '''SELECT e.*, c.especialidad, c.modalidad, c.fecha_hora, p.nombre AS paciente,
                  u.nombre AS medico
           FROM encuestas e JOIN citas c ON c.id = e.cita_id
           JOIN pacientes p ON p.id = c.paciente_id
           LEFT JOIN usuarios u ON u.id = c.medico_id
           WHERE e.respondida_en IS NOT NULL AND substr(c.fecha_hora, 1, 10) BETWEEN ? AND ?
           ORDER BY e.respondida_en DESC''',
        (desde, hasta),
    ).fetchall()


@bp.route('/encuestas')
@roles_requeridos('admin')
def lista():
    desde, hasta = leer_periodo()
    return render_template('encuestas/lista.html', respuestas=_respuestas(desde, hasta),
                           desde=desde, hasta=hasta)


@bp.route('/encuestas.csv')
@roles_requeridos('admin')
def exportar():
    desde, hasta = leer_periodo()
    salida = io.StringIO()
    escritor = csv.writer(salida)
    campos = [c for c, _, _ in PREGUNTAS_ENCUESTA]
    escritor.writerow(['fecha_cita', 'respondida_en', 'paciente', 'especialidad', 'modalidad',
                       'medico', *campos, 'nps', 'comentarios'])
    for r in _respuestas(desde, hasta):
        escritor.writerow([_celda(v) for v in (
            r['fecha_hora'], r['respondida_en'], r['paciente'], r['especialidad'], r['modalidad'],
            r['medico'], *[r[c] for c in campos], r['nps'], r['comentarios'])])
    return Response('﻿' + salida.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':
                             f'attachment; filename=encuestas_{desde}_{hasta}.csv'})
