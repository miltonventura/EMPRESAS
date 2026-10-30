import io
from datetime import date, timedelta

from clinica import create_app
from clinica.db import get_db

from .conftest import Cliente, id_de

MANANA = (date.today() + timedelta(days=1)).isoformat()


def datos_cita(**extra):
    datos = {
        'nombre': 'María Elena López', 'dui': '012345678', 'celular': '+503 7012-3456',
        'correo': 'maria@example.com', 'medio_enterado': 'Facebook / Instagram',
        'especialidad': 'Ginecología', 'medico_id': '2', 'modalidad': 'presencial',
        'fecha': MANANA, 'hora': '09:00', 'duracion_min': '30', 'motivo': 'Control anual',
    }
    datos.update(extra)
    return datos


def fila(app, sql, *params):
    with app.app_context():
        return get_db().execute(sql, params).fetchone()


def test_configuracion_inicial_crea_admin(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'DATABASE': str(tmp_path / 'db.sqlite'),
                      'UPLOAD_FOLDER': str(tmp_path / 'adj')})
    c = Cliente(app.test_client())
    assert c.get('/login').headers['Location'].endswith('/configuracion-inicial')
    r = c.post('/configuracion-inicial', {'nombre': 'Admin', 'usuario': 'admin', 'password': 'muy-segura'})
    assert r.status_code == 302
    assert c.login('admin', 'muy-segura').headers['Location'] == '/'
    # Ya no se puede volver a usar.
    assert c.get('/configuracion-inicial').status_code == 302


def test_requiere_sesion_y_csrf(cliente):
    assert '/login' in cliente.get('/pacientes/').headers['Location']
    assert cliente.c.post('/login', data={'usuario': 'admin', 'password': 'clave-admin'}).status_code == 400
    assert cliente.login('admin', 'incorrecta').status_code == 200
    assert cliente.login('admin', 'clave-admin').status_code == 302


def test_agendar_cita_crea_expediente_con_seguro_referencia_y_adjunto(app, cliente):
    cliente.login('recep', 'clave-recep')
    r = cliente.post('/citas/nueva', datos_cita(
        usa_seguro='1', cita_aseguradora='ASESUISA', cita_poliza='P-123',
        tiene_referencia='1', centro_referencia='Hospital Rosales', medico_referente='Dr. Ruiz',
        motivo_referencia='Evaluación de quiste',
        documentos=(io.BytesIO(b'%PDF-1.4 referencia'), 'referencia.pdf'),
        categoria_documento='Hoja de referencia',
    ), content_type='multipart/form-data')
    assert r.status_code == 302, r.data
    cita_id = id_de(r, r'/citas/(\d+)')

    p = fila(app, 'SELECT * FROM pacientes')
    assert (p['nombre'], p['dui'], p['celular'], p['medio_enterado'], p['aseguradora']) == (
        'María Elena López', '01234567-8', '7012-3456', 'Facebook / Instagram', 'ASESUISA')
    c = fila(app, 'SELECT * FROM citas WHERE id = ?', cita_id)
    assert c['usa_seguro'] == 1 and c['poliza'] == 'P-123'
    assert c['tiene_referencia'] == 1 and c['centro_referencia'] == 'Hospital Rosales'
    assert c['enlace_teleconsulta'] is None
    d = fila(app, 'SELECT * FROM documentos')
    assert d['nombre_original'] == 'referencia.pdf' and d['paciente_id'] == p['id']

    expediente = cliente.get(f'/pacientes/{p["id"]}').get_data(as_text=True)
    assert 'Facebook / Instagram' in expediente
    assert 'Hospital Rosales' in expediente
    assert 'referencia.pdf' in expediente
    assert 'Historial clínico' not in expediente  # recepción no ve notas clínicas

    doc = cliente.get(f'/historial/documento/{d["id"]}')
    assert doc.status_code == 200 and doc.data == b'%PDF-1.4 referencia'
    assert doc.headers['Content-Type'] == 'application/pdf'


def test_mismo_dui_reutiliza_expediente(app, cliente):
    cliente.login('recep', 'clave-recep')
    cliente.post('/citas/nueva', datos_cita())
    r = cliente.post('/citas/nueva', datos_cita(hora='10:00', celular='7999-0000'))
    assert r.status_code == 302
    assert fila(app, 'SELECT COUNT(*) FROM pacientes')[0] == 1
    assert fila(app, 'SELECT COUNT(*) FROM citas')[0] == 2
    assert fila(app, 'SELECT celular FROM pacientes')[0] == '7999-0000'


def test_validaciones_de_cita(app, cliente):
    cliente.login('recep', 'clave-recep')
    r = cliente.post('/citas/nueva', datos_cita(medio_enterado='', dui='123'))
    texto = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'por qué medio' in texto and 'El DUI debe tener 9 dígitos' in texto

    # Menor de edad: sin DUI pero con responsable.
    r = cliente.post('/citas/nueva', datos_cita(dui='', nombre='Luis Niño'))
    assert 'responsable' in r.get_data(as_text=True)
    r = cliente.post('/citas/nueva', datos_cita(dui='', nombre='Luis Niño', responsable_nombre='Ana Niño',
                                                responsable_dui='987654321', especialidad='Otorrinolaringología',
                                                medico_id='3'))
    assert r.status_code == 302
    assert fila(app, 'SELECT responsable_dui FROM pacientes')[0] == '98765432-1'

    # El médico no corresponde a la especialidad.
    r = cliente.post('/citas/nueva', datos_cita(medico_id='3'))
    assert 'no atiende Ginecología' in r.get_data(as_text=True)


def test_no_permite_traslape_de_horario(cliente):
    cliente.login('recep', 'clave-recep')
    assert cliente.post('/citas/nueva', datos_cita()).status_code == 302
    r = cliente.post('/citas/nueva', datos_cita(dui='111111111', nombre='Otra', hora='09:15'))
    assert 'se traslapa' in r.get_data(as_text=True)
    assert cliente.post('/citas/nueva', datos_cita(dui='111111111', nombre='Otra', hora='09:30')).status_code == 302


def test_teleconsulta_genera_enlace(app, cliente):
    cliente.login('recep', 'clave-recep')
    r = cliente.post('/citas/nueva', datos_cita(modalidad='teleconsulta'))
    cita_id = id_de(r, r'/citas/(\d+)')
    enlace = fila(app, 'SELECT enlace_teleconsulta FROM citas WHERE id = ?', cita_id)[0]
    assert enlace.startswith('https://meet.jit.si/Teleconsulta-')
    pagina = cliente.get(f'/citas/{cita_id}').get_data(as_text=True)
    assert enlace in pagina and 'wa.me/50370123456' in pagina


def atender_cita(app, cliente):
    cliente.login('recep', 'clave-recep')
    cita_id = id_de(cliente.post('/citas/nueva', datos_cita()), r'/citas/(\d+)')
    paciente_id = fila(app, 'SELECT paciente_id FROM citas')[0]
    url = f'/historial/paciente/{paciente_id}/consulta/nueva?cita_id={cita_id}'
    assert cliente.get(url).status_code == 403

    cliente.login('drgin', 'clave-medico')
    r = cliente.post(url, {'especialidad': 'Ginecología', 'motivo': 'Control anual',
                           'diagnostico': 'Paciente sana', 'presion_arterial': '110/70',
                           'documentos': (io.BytesIO(b'png'), 'eco.png'),
                           'categoria_documento': 'Imagen / radiografía / ultrasonografía'},
                     content_type='multipart/form-data')
    assert r.status_code == 302
    assert fila(app, 'SELECT estado FROM citas')[0] == 'atendida'
    assert fila(app, 'SELECT consulta_id FROM documentos')[0] is not None
    token = fila(app, 'SELECT token FROM encuestas WHERE cita_id = ?', cita_id)[0]
    assert 'Paciente sana' in cliente.get(f'/pacientes/{paciente_id}').get_data(as_text=True)
    # Volver a "atender" lleva a la consulta ya registrada.
    assert '/historial/consulta/' in cliente.get(url).headers['Location']
    return token


def test_consulta_marca_atendida_y_encuesta(app, cliente):
    assert atender_cita(app, cliente)


def test_encuesta_publica_e_indicadores(app, cliente):
    token = atender_cita(app, cliente)
    anonimo = Cliente(app.test_client())
    pagina = anonimo.get(f'/encuesta/{token}')
    assert pagina.status_code == 200 and 'María' in pagina.get_data(as_text=True)

    incompleta = anonimo.post(f'/encuesta/{token}', {'calif_medico': '5'})
    assert 'Responda' in incompleta.get_data(as_text=True)

    respuestas = {'calif_medico': '5', 'calif_recepcion': '4', 'calif_enfermeria': 'na',
                  'calif_puntualidad': '3', 'calif_instalaciones': '5', 'calif_general': '5',
                  'nps': '10', 'comentarios': '=Excelente atención'}
    assert 'Recibimos sus respuestas' in anonimo.post(f'/encuesta/{token}', respuestas).get_data(as_text=True)
    assert 'ya fue respondida' in anonimo.post(f'/encuesta/{token}', dict(respuestas, nps='0')).get_data(as_text=True)
    e = fila(app, 'SELECT * FROM encuestas')
    assert (e['calif_medico'], e['calif_enfermeria'], e['nps']) == (5, None, 10)
    assert anonimo.get('/encuesta/no-existe').status_code == 404

    hasta = (date.today() + timedelta(days=30)).isoformat()
    cliente.login('recep', 'clave-recep')
    assert cliente.get('/reportes/').status_code == 403
    cliente.login('admin', 'clave-admin')
    indicadores = cliente.get(f'/reportes/?desde={date.today().replace(day=1)}&hasta={hasta}').get_data(as_text=True)
    assert '5.00' in indicadores and '100%' in indicadores and 'Facebook / Instagram' in indicadores
    assert 'Dra. Gómez' in indicadores

    csv = cliente.get(f'/encuestas.csv?desde={date.today()}&hasta={hasta}').get_data(as_text=True)
    assert "'=Excelente atención" in csv


def test_adjuntos_rechaza_extensiones_no_permitidas(app, cliente):
    cliente.login('recep', 'clave-recep')
    cliente.post('/citas/nueva', datos_cita())
    r = cliente.post('/historial/paciente/1/documentos',
                     {'categoria': 'Otro', 'documentos': (io.BytesIO(b'MZ'), 'virus.exe')},
                     content_type='multipart/form-data', follow_redirects=True)
    assert 'tipo de archivo no permitido' in r.get_data(as_text=True)
    assert fila(app, 'SELECT COUNT(*) FROM documentos')[0] == 0
    anonimo = Cliente(app.test_client())
    assert anonimo.get('/historial/documento/1').status_code == 302


def test_paginas_cargan(app, cliente):
    cliente.login('admin', 'clave-admin')
    cliente.post('/citas/nueva', datos_cita(modalidad='teleconsulta'))
    for url in ['/', '/citas/', f'/citas/?fecha={MANANA}', '/citas/nueva', '/citas/1', '/citas/1/editar',
                '/pacientes/', '/pacientes/?q=maria', '/pacientes/?q=7012', '/pacientes/nuevo',
                '/pacientes/1', '/pacientes/1/editar', '/historial/paciente/1/consulta/nueva',
                '/reportes/', '/encuestas', '/usuarios', '/usuarios/nuevo', '/usuarios/2']:
        r = cliente.get(url)
        assert r.status_code == 200, url
    assert cliente.get('/pacientes/999').status_code == 404


def test_reprogramar_y_cancelar(app, cliente):
    cliente.login('recep', 'clave-recep')
    cita_id = id_de(cliente.post('/citas/nueva', datos_cita()), r'/citas/(\d+)')
    r = cliente.post(f'/citas/{cita_id}/editar', datos_cita(hora='11:00', modalidad='teleconsulta'))
    assert r.status_code == 302
    c = fila(app, 'SELECT * FROM citas')
    assert c['fecha_hora'].endswith('11:00') and c['enlace_teleconsulta']
    cliente.post(f'/citas/{cita_id}/estado', {'estado': 'cancelada', 'volver': '//malicioso.com'})
    assert fila(app, 'SELECT estado FROM citas')[0] == 'cancelada'
    # El horario cancelado queda libre.
    assert cliente.post('/citas/nueva', datos_cita(dui='111111111', nombre='Otra', hora='11:00')).status_code == 302
