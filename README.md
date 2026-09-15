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
