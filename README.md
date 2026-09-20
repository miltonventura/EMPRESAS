# EMPRESAS

Búsqueda de empresas — base unificada de OpenStreetMap para San Salvador,
publicada como capa vectorial de puntos.

## Contenido

| Ruta | Descripción |
|---|---|
| `datos/base_unificada_osm_san_salvador.xlsx` | Excel de origen (9.983 registros) |
| `scripts/excel_a_puntos.py` | Convierte el Excel en capa de puntos |
| `salida/empresas_san_salvador.gpkg` | **GeoPackage — formato recomendado** |
| `salida/empresas_san_salvador.geojson` | GeoJSON (web, se previsualiza en GitHub) |
| `salida/shapefile_empresas_san_salvador.zip` | Shapefile comprimido |

## La capa

- **9.983 puntos**, uno por objeto OSM. Ninguna fila se descartó.
- **CRS: EPSG:4326** (WGS84 lat/lon), el mismo que usa OSM.
- Extensión: lon −89,2788 a −89,1574 · lat 13,6332 a 13,8769.

### Campos

| Campo | Shapefile | Descripción |
|---|---|---|
| `categorias` | `categorias` | Categorías separadas por ` \| ` (18 valores distintos) |
| `subcategorias` | `subcateg` | Etiquetas OSM crudas, ej. `amenity=restaurant` |
| `categoria_principal` | `cat_princ` | Primera categoría — campo simple para simbolizar en QGIS |
| `n_categorias` | `n_categ` | Cuántas categorías tiene el objeto (1 a 7) |
| `nombre` | `nombre` | Nombre OSM (vacío en 4.325 objetos: árboles, bancas, edificios sin nombre) |
| `distrito` | `distrito` | Siempre `San Salvador` en esta base |
| `latitud`, `longitud` | igual | Coordenadas originales, conservadas como atributo |
| `osm_tipo`, `osm_id` | igual | Identificador OSM (`way` 5.399 · `node` 4.139 · `relation` 445) |
| `url_osm` | `url_osm` | Enlace al objeto en openstreetmap.org |

En Shapefile los nombres se acortan a 10 caracteres (límite del formato); el
GeoPackage y el GeoJSON conservan los nombres completos.

## Regenerar la capa

```bash
pip install pandas openpyxl geopandas
python scripts/excel_a_puntos.py                      # usa datos/ y escribe en salida/
python scripts/excel_a_puntos.py otro.xlsx -o /tmp/x  # otra entrada / otra salida
```

El script tolera coma decimal, separa a `salida/filas_descartadas.csv` las filas
sin coordenada válida y avisa si algún punto cae fuera de El Salvador (síntoma
típico de lat/lon invertidas).

## Nota sobre `way` y `relation`

Los objetos OSM de tipo `way` y `relation` son en origen líneas o polígonos
(edificios, parcelas, parques). Aquí están representados por un único punto —
el centroide que ya venía calculado en el Excel. Sirve para búsqueda y
localización; si necesitás las geometrías reales de esos 5.844 objetos, hay que
volver a consultarlos en OSM por su `osm_id`.
