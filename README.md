# EMPRESAS
Búsqueda de empresas

## osm_categorias.py — categorías de OpenStreetMap

Script en Python (solo librería estándar, Python 3.8+) que consulta OpenStreetMap
para conocer en detalle las categorías que maneja (comercios, empresas, oficinas,
centros comerciales, parques, turismo, salud, etc.).

```bash
# Catálogo global de las claves principales (top 50 valores por clave)
python osm_categorias.py

# Solo comercios y oficinas, 200 valores por clave, exportando a JSON y CSV
python osm_categorias.py --claves shop office --limite 200 --salida categorias

# Además, contar cuántos elementos hay de cada categoría en una ciudad
python osm_categorias.py --claves shop amenity --area "Bogotá"

# Listar TODAS las claves que existen en OSM ordenadas por uso
python osm_categorias.py --todas-las-claves --limite 500
```

Fuentes: [Taginfo](https://taginfo.openstreetmap.org) (catálogo global) y
[Overpass API](https://overpass-api.de) (conteos por área). Ninguna requiere clave.

## osm_categorias_el_salvador.py — categorías de OSM en El Salvador

Genera un CSV con todas las categorías (clave=valor) que OpenStreetMap tiene
registradas dentro de El Salvador, con cantidad de elementos, ejemplos de nombres,
descripción en español y enlace al wiki.

```bash
python osm_categorias_el_salvador.py                 # todo el país, todas las claves
python osm_categorias_el_salvador.py --sin-edificios # omite building=* (más rápido)
python osm_categorias_el_salvador.py --claves shop office amenity leisure
```

Salida: `categorias_el_salvador.csv` (detalle), `categorias_el_salvador_resumen.csv`
(totales por grupo), `lugares_el_salvador.csv` (cada lugar con nombre, dirección,
contacto y coordenadas) y `categorias_el_salvador.json`. Con `--guardar-crudo` se
conservan además las respuestas JSON originales de Overpass en `osm_crudo/`.
