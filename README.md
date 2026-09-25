# EMPRESAS
Búsqueda de empresas

## Ruleta de rifa (`ruleta-rifa/`)

Aplicación de una sola página para sortear premios entre los asistentes de un evento. No necesita instalación: abre `ruleta-rifa/index.html` en cualquier navegador.

1. Carga la base de datos de asistentes (CSV, TXT o Excel `.xlsx`/`.xls`/`.ods`) arrastrando el archivo, o pega la lista copiada desde Excel.
2. Elige qué columna tiene el nombre y, si quieres, el apellido y un dato visible (empresa, número de boleto…). Los repetidos se omiten.
3. Escribe el premio y pulsa **Girar la ruleta** (o la barra espaciadora).
4. Confirma al ganador o márcalo como **No está presente** para volver a sortear el mismo premio.

- El ganador se elige con `crypto.getRandomValues` (aleatorio criptográfico) antes de que empiece la animación.
- Los datos no salen del navegador; la rifa se guarda en el equipo para no perderla si se recarga la página.
- En la pestaña **Ganadores** se puede copiar la lista para pegarla en Excel, deshacer el último sorteo o reiniciar la rifa.
- **Pantalla completa** muestra solo la ruleta, ideal para proyectar.
- La ruleta empieza vacía: no muestra ningún nombre hasta que se carga la lista de asistentes.

`ruleta-rifa/ejemplo-asistentes.csv` es un archivo de prueba con el formato esperado.
