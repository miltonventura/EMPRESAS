"""Inicio de sesión del personal y administración de usuarios."""

import functools

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .catalogos import ESPECIALIDADES, ROLES
from .db import crear_usuario, get_db
from .validadores import texto

bp = Blueprint('auth', __name__)


@bp.before_app_request
def cargar_usuario():
    g.user = None
    usuario_id = session.get('usuario_id')
    if usuario_id is not None:
        g.user = get_db().execute(
            'SELECT * FROM usuarios WHERE id = ? AND activo = 1', (usuario_id,)
        ).fetchone()


def roles_requeridos(*roles):
    """Exige sesión iniciada y, si se indican, alguno de los roles dados."""
    def decorador(vista):
        @functools.wraps(vista)
        def envuelta(**kwargs):
            if g.user is None:
                return redirect(url_for('auth.login', next=request.path))
            if roles and g.user['rol'] not in roles:
                abort(403)
            return vista(**kwargs)
        return envuelta
    return decorador


login_requerido = roles_requeridos()


def puede_ver_clinico():
    """Las notas clínicas solo las ven médicos y administradores."""
    return g.user is not None and g.user['rol'] in ('admin', 'medico')


@bp.app_context_processor
def inyectar_permisos():
    return {'puede_ver_clinico': puede_ver_clinico}


def _hay_usuarios():
    return get_db().execute('SELECT 1 FROM usuarios LIMIT 1').fetchone() is not None


@bp.route('/login', methods=('GET', 'POST'))
def login():
    if not _hay_usuarios():
        return redirect(url_for('auth.configuracion_inicial'))
    if request.method == 'POST':
        usuario = get_db().execute(
            'SELECT * FROM usuarios WHERE usuario = ? AND activo = 1',
            (texto(request.form, 'usuario') or '',),
        ).fetchone()
        if usuario is None or not check_password_hash(usuario['password_hash'],
                                                      request.form.get('password', '')):
            flash('Usuario o contraseña incorrectos.', 'error')
        else:
            csrf = session.get('_csrf')
            session.clear()
            if csrf:
                session['_csrf'] = csrf
            session['usuario_id'] = usuario['id']
            destino = request.args.get('next', '')
            if not destino.startswith('/') or destino.startswith('//'):
                destino = url_for('inicio')
            return redirect(destino)
    return render_template('auth/login.html')


@bp.route('/logout', methods=('POST',))
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@bp.route('/configuracion-inicial', methods=('GET', 'POST'))
def configuracion_inicial():
    """Primer uso: crea la cuenta de administrador cuando aún no existe ningún usuario."""
    if _hay_usuarios():
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        errores = _validar_usuario(request.form, nuevo=True)
        if errores:
            for e in errores:
                flash(e, 'error')
        else:
            crear_usuario(texto(request.form, 'usuario'), texto(request.form, 'nombre'),
                          request.form['password'], 'admin')
            flash('Administrador creado. Inicie sesión.', 'ok')
            return redirect(url_for('auth.login'))
    return render_template('auth/configuracion_inicial.html')


def _validar_usuario(form, nuevo):
    errores = []
    if nuevo:
        usuario = texto(form, 'usuario')
        if not usuario:
            errores.append('El nombre de usuario es obligatorio.')
        elif get_db().execute('SELECT 1 FROM usuarios WHERE usuario = ?', (usuario,)).fetchone():
            errores.append('Ese nombre de usuario ya existe.')
    if not texto(form, 'nombre'):
        errores.append('El nombre completo es obligatorio.')
    password = form.get('password', '')
    if (nuevo or password) and len(password) < 8:
        errores.append('La contraseña debe tener al menos 8 caracteres.')
    if 'rol' in form:
        if form['rol'] not in ROLES:
            errores.append('Rol no válido.')
        elif form['rol'] == 'medico' and form.get('especialidad') not in ESPECIALIDADES:
            errores.append('Seleccione la especialidad del médico.')
    return errores


@bp.route('/usuarios')
@roles_requeridos('admin')
def usuarios():
    filas = get_db().execute('SELECT * FROM usuarios ORDER BY activo DESC, nombre').fetchall()
    return render_template('auth/usuarios.html', usuarios=filas)


@bp.route('/usuarios/nuevo', methods=('GET', 'POST'))
@roles_requeridos('admin')
def usuario_nuevo():
    if request.method == 'POST':
        errores = _validar_usuario(request.form, nuevo=True)
        if not errores:
            rol = request.form['rol']
            crear_usuario(texto(request.form, 'usuario'), texto(request.form, 'nombre'),
                          request.form['password'], rol,
                          request.form.get('especialidad') if rol == 'medico' else None)
            flash('Usuario creado.', 'ok')
            return redirect(url_for('auth.usuarios'))
        for e in errores:
            flash(e, 'error')
    return render_template('auth/usuario_form.html', u=None, form=request.form)


@bp.route('/usuarios/<int:usuario_id>', methods=('GET', 'POST'))
@roles_requeridos('admin')
def usuario_editar(usuario_id):
    db = get_db()
    u = db.execute('SELECT * FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    if u is None:
        abort(404)
    if request.method == 'POST':
        errores = _validar_usuario(request.form, nuevo=False)
        activo = 1 if request.form.get('activo') else 0
        if u['id'] == g.user['id'] and (not activo or request.form.get('rol') != 'admin'):
            errores.append('No puede desactivar ni quitarse el rol de administrador a sí mismo.')
        if not errores:
            rol = request.form['rol']
            db.execute(
                'UPDATE usuarios SET nombre = ?, rol = ?, especialidad = ?, activo = ? WHERE id = ?',
                (texto(request.form, 'nombre'), rol,
                 request.form.get('especialidad') if rol == 'medico' else None, activo, u['id']),
            )
            if request.form.get('password'):
                db.execute('UPDATE usuarios SET password_hash = ? WHERE id = ?',
                           (generate_password_hash(request.form['password']), u['id']))
            db.commit()
            flash('Usuario actualizado.', 'ok')
            return redirect(url_for('auth.usuarios'))
        for e in errores:
            flash(e, 'error')
    return render_template('auth/usuario_form.html', u=u, form=request.form or dict(u))
