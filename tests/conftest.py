import re

import pytest

from clinica import create_app
from clinica.db import crear_usuario


@pytest.fixture
def app(tmp_path):
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'pruebas',
        'DATABASE': str(tmp_path / 'clinica.sqlite'),
        'UPLOAD_FOLDER': str(tmp_path / 'adjuntos'),
        'SERVER_NAME': 'clinica.test',
    })
    with app.app_context():
        crear_usuario('admin', 'Ana Administradora', 'clave-admin', 'admin')
        crear_usuario('drgin', 'Dra. Gómez', 'clave-medico', 'medico', 'Ginecología')
        crear_usuario('drorl', 'Dr. Pérez', 'clave-medico', 'medico', 'Otorrinolaringología')
        crear_usuario('recep', 'Rosa Recepción', 'clave-recep', 'recepcion')
    return app


class Cliente:
    """Cliente de pruebas que incluye automáticamente el token CSRF en los POST."""

    def __init__(self, client):
        self.c = client

    def token(self):
        with self.c.session_transaction() as s:
            s.setdefault('_csrf', 'token-de-prueba')
            return s['_csrf']

    def get(self, *a, **kw):
        return self.c.get(*a, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault('_csrf', self.token())
        return self.c.post(url, data=data, **kw)

    def login(self, usuario, password):
        return self.post('/login', {'usuario': usuario, 'password': password})


@pytest.fixture
def cliente(app):
    return Cliente(app.test_client())


def id_de(respuesta, patron):
    return int(re.search(patron, respuesta.headers['Location']).group(1))
