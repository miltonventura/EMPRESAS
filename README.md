# Sistema de gestión de la clínica

Aplicación web para una clínica de **Medicina General, Otorrinolaringología y Ginecología**:
expedientes de pacientes, agenda de citas presenciales y teleconsultas, historial clínico con
documentos adjuntos y medición de la experiencia del paciente.

## Funciones

| Necesidad | Dónde se cubre |
|---|---|
| Un expediente por paciente | **Expedientes** (`EXP-000001`, …). Búsqueda por nombre, DUI o celular. |
| Agendar citas pidiendo datos básicos | **Agendar cita**: nombre, DUI, celular, correo, si usará seguro médico (aseguradora y póliza) y si viene referido de otro centro (centro, médico y motivo). Si el DUI ya existe, la cita se agrega a ese expediente. Menores sin DUI se registran con el DUI de su responsable. Se evita el traslape de horarios por médico. |
| Teleconsultas | Al elegir modalidad *Teleconsulta* se genera un enlace de videollamada único, que se envía al paciente por WhatsApp con un clic. |
| Adjuntar documentos y exámenes | En el expediente, al agendar la cita (p. ej. hoja de referencia) o al registrar la consulta. PDF, imágenes, Word, Excel, DICOM; hasta 25 MB por envío. |
| Historial clínico | Notas de consulta con signos vitales, examen físico, diagnóstico, tratamiento e indicaciones. Imprimibles. |
| Medio por el que se enteró | Campo obligatorio en cada expediente (redes sociales, recomendación, Google, referencia médica, aseguradora, etc.), visible en el expediente y resumido en **Indicadores**. |
| Experiencia del paciente | Al atender una cita se crea una encuesta con enlace único (por WhatsApp o en una tableta en recepción): calificación del médico, recepción, enfermería, puntualidad, instalaciones/videollamada, satisfacción general, NPS (0–10) y comentarios. **Indicadores** muestra promedios por especialidad, médico y modalidad, NPS y tasa de respuesta; las respuestas se exportan a CSV. |

### Roles

- **Administrador**: todo, incluidos usuarios, indicadores y encuestas.
- **Médico**: agenda (por defecto la suya), expedientes, notas clínicas y documentos.
- **Recepción**: agenda, expedientes y documentos. **No** ve notas clínicas, alergias ni antecedentes.

## Instalación

Requiere Python 3.10 o superior.

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
flask --app clinica run
```

Abra <http://127.0.0.1:5000>. La primera vez se pide crear la cuenta de administrador; desde
**Usuarios** se registran médicos (con su especialidad) y personal de recepción. También puede
crear usuarios desde la terminal:

```bash
flask --app clinica crear-usuario
```

### Configuración (variables de entorno)

| Variable | Uso | Valor por defecto |
|---|---|---|
| `NOMBRE_CLINICA` | Nombre que aparece en pantallas, encuestas y mensajes | `Clínica Médica` |
| `TELECONSULTA_BASE_URL` | Servidor de videollamadas (Jitsi) | `https://meet.jit.si` |
| `SECRET_KEY` | Clave de sesiones; si no se define se genera en `instance/secret_key` | — |

Los datos se guardan en la carpeta `instance/`: la base de datos `clinica.sqlite` y los documentos
en `instance/adjuntos/`. **Respalde esa carpeta con regularidad.**

### Teleconsultas

Los enlaces usan [Jitsi Meet](https://jitsi.org/), que funciona en el navegador o en la app sin que
el paciente cree una cuenta. En el servidor público `meet.jit.si` el médico debe iniciar sesión
(Google, GitHub, etc.) para abrir la sala. Para uso intensivo o mayor privacidad se recomienda un
servidor Jitsi propio y apuntar `TELECONSULTA_BASE_URL` a él.

### Producción

Use un servidor WSGI detrás de HTTPS, por ejemplo:

```bash
pip install waitress
```

```bash
waitress-serve --call clinica:create_app
```

Como la aplicación maneja información médica, publíquela solo con HTTPS y defina
`SESSION_COOKIE_SECURE = True` en `instance/config.py`.

## Pruebas

```bash
pip install pytest
```

```bash
python -m pytest
```
