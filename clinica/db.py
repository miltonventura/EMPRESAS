import sqlite3

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

from .catalogos import ESPECIALIDADES, ROLES


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Crea las tablas que falten. Es seguro ejecutarlo varias veces."""
    db = get_db()
    with current_app.open_resource('schema.sql') as f:
        db.executescript(f.read().decode('utf-8'))


def crear_usuario(usuario, nombre, password, rol, especialidad=None):
    db = get_db()
    cur = db.execute(
        'INSERT INTO usuarios (usuario, nombre, password_hash, rol, especialidad) VALUES (?, ?, ?, ?, ?)',
        (usuario, nombre, generate_password_hash(password), rol, especialidad),
    )
    db.commit()
    return cur.lastrowid


@click.command('init-db')
def init_db_command():
    """Crea las tablas de la base de datos."""
    init_db()
    click.echo('Base de datos lista.')


@click.command('crear-usuario')
@click.option('--usuario', prompt=True)
@click.option('--nombre', prompt='Nombre completo')
@click.option('--rol', type=click.Choice(list(ROLES)), prompt=True)
@click.option('--especialidad', type=click.Choice(ESPECIALIDADES), default=None,
              help='Solo para médicos.')
@click.password_option()
def crear_usuario_command(usuario, nombre, rol, especialidad, password):
    """Crea un usuario del personal de la clínica."""
    init_db()
    if len(password) < 8:
        raise click.BadParameter('la contraseña debe tener al menos 8 caracteres', param_hint='password')
    crear_usuario(usuario, nombre, password, rol, especialidad if rol == 'medico' else None)
    click.echo(f'Usuario {usuario} creado.')


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(crear_usuario_command)
