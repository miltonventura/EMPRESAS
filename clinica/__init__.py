"""Aplicación de gestión de la clínica: expedientes, citas, teleconsultas y satisfacción."""

import os
import secrets
from datetime import date, datetime

from flask import Flask, abort, render_template, request, session

from . import catalogos, db


def _clave_secreta(app):
    """Usa SECRET_KEY del entorno o genera una y la guarda en la carpeta instance."""
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    ruta = os.path.join(app.instance_path, 'secret_key')
    if not os.path.exists(ruta):
        with open(ruta, 'w') as f:
            f.write(secrets.token_hex(32))
        os.chmod(ruta, 0o600)
    with open(ruta) as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, 'clinica.sqlite'),
        UPLOAD_FOLDER=os.path.join(app.instance_path, 'adjuntos'),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        NOMBRE_CLINICA=os.environ.get('NOMBRE_CLINICA', 'Clínica Médica'),
        TELECONSULTA_BASE_URL=os.environ.get('TELECONSULTA_BASE_URL', 'https://meet.jit.si'),
        CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if test_config is None:
        app.config.from_pyfile('config.py', silent=True)
    else:
        app.config.update(test_config)
    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = _clave_secreta(app)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.init_db()

    _registrar_csrf(app)
    _registrar_filtros(app)
    _registrar_errores(app)

    from . import auth, citas, encuestas, historial, pacientes, reportes
    app.register_blueprint(auth.bp)
    app.register_blueprint(pacientes.bp)
    app.register_blueprint(citas.bp)
    app.register_blueprint(historial.bp)
    app.register_blueprint(encuestas.bp)
    app.register_blueprint(reportes.bp)
    app.add_url_rule('/', endpoint='inicio', view_func=reportes.inicio)

    return app


def _registrar_csrf(app):
    def csrf_token():
        if '_csrf' not in session:
            session['_csrf'] = secrets.token_urlsafe(32)
        return session['_csrf']

    @app.before_request
    def proteger_csrf():
        if request.method == 'POST' and app.config['CSRF_ENABLED']:
            esperado = session.get('_csrf')
            recibido = request.form.get('_csrf', '')
            if not esperado or not secrets.compare_digest(esperado, recibido):
                abort(400, 'El formulario expiró. Recargue la página e intente de nuevo.')

    app.jinja_env.globals['csrf_token'] = csrf_token


def _registrar_errores(app):
    mensajes = {
        400: ('Solicitud no válida', 'El formulario expiró o está incompleto. Recargue la página e intente de nuevo.'),
        403: ('Acceso restringido', 'Su usuario no tiene permiso para ver esta sección.'),
        404: ('No encontrado', 'La página o el registro solicitado no existe.'),
        413: ('Archivo demasiado grande', 'Los archivos adjuntos superan el máximo de 25 MB por envío.'),
    }

    def manejar(error):
        titulo, mensaje = mensajes[error.code]
        return render_template('error.html', titulo=titulo, mensaje=mensaje), error.code

    for codigo in mensajes:
        app.register_error_handler(codigo, manejar)


def _registrar_filtros(app):
    app.jinja_env.globals.update(
        catalogos=catalogos,
        nombre_clinica=lambda: app.config['NOMBRE_CLINICA'],
        hoy=lambda: date.today().isoformat(),
    )

    @app.template_filter('fecha')
    def fecha(valor):
        if not valor:
            return ''
        try:
            if 'T' in valor:
                return datetime.fromisoformat(valor).strftime('%d/%m/%Y %H:%M')
            return datetime.fromisoformat(valor).strftime('%d/%m/%Y')
        except ValueError:
            return valor

    @app.template_filter('hora')
    def hora(valor):
        return valor[11:16] if valor and len(valor) >= 16 else ''

    @app.template_filter('expediente')
    def expediente(paciente_id):
        return f'EXP-{int(paciente_id):06d}'

    @app.template_filter('edad')
    def edad(fecha_nacimiento):
        if not fecha_nacimiento:
            return ''
        try:
            nac = date.fromisoformat(fecha_nacimiento)
        except ValueError:
            return ''
        hoy = date.today()
        anios = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
        return f'{anios} años'

    @app.template_filter('tamano')
    def tamano(n):
        for unidad in ('B', 'KB', 'MB'):
            if n < 1024:
                return f'{n:.0f} {unidad}'
            n /= 1024
        return f'{n:.1f} GB'
