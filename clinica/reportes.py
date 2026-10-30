"""Panel de inicio e indicadores: satisfacción, origen de pacientes y citas."""

from datetime import date

from flask import Blueprint, g, render_template, request

from .auth import login_requerido, roles_requeridos
from .catalogos import ESTADOS_CITA, MODALIDADES, PREGUNTAS_ENCUESTA
from .db import get_db
from .validadores import fecha_valida

bp = Blueprint('reportes', __name__, url_prefix='/reportes')


def leer_periodo():
    """Periodo de los filtros ?desde=&hasta=; por defecto, el mes en curso."""
    hoy = date.today()
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    if not fecha_valida(desde):
        desde = hoy.replace(day=1).isoformat()
    if not fecha_valida(hasta):
        hasta = hoy.isoformat()
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


@login_requerido
def inicio():
    db = get_db()
    hoy = date.today().isoformat()
    filtro, params = '', [hoy]
    if g.user['rol'] == 'medico':
        filtro, params = ' AND c.medico_id = ?', [hoy, g.user['id']]
    citas_hoy = db.execute(
        f'''SELECT c.*, p.nombre AS paciente, u.nombre AS medico FROM citas c
            JOIN pacientes p ON p.id = c.paciente_id LEFT JOIN usuarios u ON u.id = c.medico_id
            WHERE substr(c.fecha_hora, 1, 10) = ?{filtro} ORDER BY c.fecha_hora''',
        params,
    ).fetchall()
    resumen = {
        'pacientes': db.execute('SELECT COUNT(*) FROM pacientes').fetchone()[0],
        'citas_hoy': len(citas_hoy),
        'teleconsultas_hoy': sum(1 for c in citas_hoy if c['modalidad'] == 'teleconsulta'),
        'pendientes_hoy': sum(1 for c in citas_hoy if c['estado'] in ('programada', 'confirmada')),
        'encuestas_sin_responder': db.execute(
            'SELECT COUNT(*) FROM encuestas WHERE respondida_en IS NULL').fetchone()[0],
    }
    return render_template('reportes/inicio.html', citas_hoy=citas_hoy, resumen=resumen)


def _nps(valores):
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    promotores = sum(1 for v in valores if v >= 9)
    detractores = sum(1 for v in valores if v <= 6)
    return round(100 * (promotores - detractores) / len(valores))


def _promedios(filas):
    resultado = {}
    for campo, _, _ in PREGUNTAS_ENCUESTA:
        valores = [f[campo] for f in filas if f[campo] is not None]
        resultado[campo] = round(sum(valores) / len(valores), 2) if valores else None
    resultado['nps'] = _nps([f['nps'] for f in filas])
    resultado['n'] = len(filas)
    return resultado


def _agrupar(filas, clave):
    grupos = {}
    for f in filas:
        grupos.setdefault(f[clave] or 'Sin asignar', []).append(f)
    return {nombre: _promedios(grupo) for nombre, grupo in sorted(grupos.items())}


def _conteo(sql, params, nombres=None):
    nombres = nombres or {}
    filas = get_db().execute(sql, params).fetchall()
    total = sum(f['n'] for f in filas) or 1
    return [{'etiqueta': nombres.get(f['etiqueta'], f['etiqueta']), 'n': f['n'],
             'pct': round(100 * f['n'] / total)}
            for f in filas]


@bp.route('/')
@roles_requeridos('admin')
def indicadores():
    desde, hasta = leer_periodo()
    db = get_db()
    periodo = (desde, hasta)

    respuestas = db.execute(
        '''SELECT e.*, c.especialidad, c.modalidad, u.nombre AS medico
           FROM encuestas e JOIN citas c ON c.id = e.cita_id
           LEFT JOIN usuarios u ON u.id = c.medico_id
           WHERE e.respondida_en IS NOT NULL AND substr(c.fecha_hora, 1, 10) BETWEEN ? AND ?''',
        periodo,
    ).fetchall()
    enviadas = db.execute(
        '''SELECT COUNT(*) FROM encuestas e JOIN citas c ON c.id = e.cita_id
           WHERE substr(c.fecha_hora, 1, 10) BETWEEN ? AND ?''',
        periodo,
    ).fetchone()[0]
    satisfaccion = {
        'general': _promedios(respuestas),
        'por_especialidad': _agrupar(respuestas, 'especialidad'),
        'por_medico': _agrupar(respuestas, 'medico'),
        'por_modalidad': _agrupar(respuestas, 'modalidad'),
        'enviadas': enviadas,
        'tasa_respuesta': round(100 * len(respuestas) / enviadas) if enviadas else None,
        'distribucion_general': [
            sum(1 for r in respuestas if r['calif_general'] == v) for v in range(1, 6)],
    }

    medios_periodo = _conteo(
        '''SELECT medio_enterado AS etiqueta, COUNT(*) AS n FROM pacientes
           WHERE substr(creado, 1, 10) BETWEEN ? AND ? GROUP BY medio_enterado ORDER BY n DESC''',
        periodo,
    )
    medios_total = _conteo(
        '''SELECT medio_enterado AS etiqueta, COUNT(*) AS n FROM pacientes
           GROUP BY medio_enterado ORDER BY n DESC''',
        (),
    )

    filtro_citas = 'WHERE substr(fecha_hora, 1, 10) BETWEEN ? AND ?'
    citas = {
        'por_estado': _conteo(f'SELECT estado AS etiqueta, COUNT(*) AS n FROM citas {filtro_citas} '
                              'GROUP BY estado ORDER BY n DESC', periodo, ESTADOS_CITA),
        'por_especialidad': _conteo(f'SELECT especialidad AS etiqueta, COUNT(*) AS n FROM citas '
                                    f'{filtro_citas} GROUP BY especialidad ORDER BY n DESC', periodo),
        'por_modalidad': _conteo(f'SELECT modalidad AS etiqueta, COUNT(*) AS n FROM citas '
                                 f'{filtro_citas} GROUP BY modalidad ORDER BY n DESC', periodo, MODALIDADES),
        'seguro': _conteo(f"SELECT CASE usa_seguro WHEN 1 THEN 'Con seguro médico' "
                          f"ELSE 'Sin seguro (privado)' END AS etiqueta, COUNT(*) AS n FROM citas "
                          f'{filtro_citas} GROUP BY usa_seguro ORDER BY n DESC', periodo),
        'aseguradoras': _conteo(f'SELECT aseguradora AS etiqueta, COUNT(*) AS n FROM citas '
                                f'{filtro_citas} AND usa_seguro = 1 GROUP BY aseguradora '
                                'ORDER BY n DESC', periodo),
        'referencias': _conteo(f'SELECT centro_referencia AS etiqueta, COUNT(*) AS n FROM citas '
                               f'{filtro_citas} AND tiene_referencia = 1 GROUP BY centro_referencia '
                               'ORDER BY n DESC', periodo),
    }
    return render_template('reportes/indicadores.html', desde=desde, hasta=hasta,
                           satisfaccion=satisfaccion, medios_periodo=medios_periodo,
                           medios_total=medios_total, citas=citas)
