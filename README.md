# EMPRESAS — descarga de OpenStreetMap por categoria

Scripts para consultar y descargar los datos de OpenStreetMap del distrito de
**San Salvador**, El Salvador, una categoria por archivo.

Todos los archivos son independientes y comparten la misma estructura: bajan la
frontera del distrito (y la guardan en cache), consultan Overpass dentro de esa
area y dejan los resultados en la carpeta `datos/`, en CSV y GeoJSON, con las
mismas columnas en todos los casos.

## Uso

```bash
pip install requests
python3 descargar_shop_san_salvador.py
```

Cada archivo se corre por su cuenta. La frontera del distrito se descarga una
sola vez: el primero que se corra deja `datos/_frontera_san_salvador.json` y los
demas la reutilizan.

## Categorias

| Archivo | Llave de OSM | Salida en `datos/` |
|---|---|---|
| `descargar_shop_san_salvador.py`       | `shop`       | `comercios_san_salvador.csv` |
| `descargar_office_san_salvador.py`     | `office`     | `oficinas_san_salvador.csv` |
| `descargar_craft_san_salvador.py`      | `craft`      | `oficios_san_salvador.csv` |
| `descargar_brand_san_salvador.py`      | `brand`      | `marcas_san_salvador.csv` |
| `descargar_industrial_san_salvador.py` | `industrial` | `industrias_san_salvador.csv` |
| `descargar_amenity_san_salvador.py`    | `amenity`    | `servicios_san_salvador.csv` |
| `descargar_leisure_san_salvador.py`    | `leisure`    | `recreacion_san_salvador.csv` |
| `descargar_tourism_san_salvador.py`    | `tourism`    | `turismo_san_salvador.csv` |
| `descargar_sport_san_salvador.py`      | `sport`      | `deportes_san_salvador.csv` |
| `descargar_cuisine_san_salvador.py`    | `cuisine`    | `gastronomia_san_salvador.csv` |
| `descargar_club_san_salvador.py`       | `club`       | `clubes_san_salvador.csv` |
| `descargar_healthcare_san_salvador.py` | `healthcare` | `salud_san_salvador.csv` |
| `descargar_building_san_salvador.py`   | `building`   | `edificaciones_san_salvador.csv` |
| `descargar_landuse_san_salvador.py`    | `landuse`    | `usos_de_suelo_san_salvador.csv` |
| `descargar_place_san_salvador.py`      | `place`      | `lugares_san_salvador.csv` |
| `descargar_natural_san_salvador.py`    | `natural`    | `naturaleza_san_salvador.csv` |
| `descargar_historic_san_salvador.py`   | `historic`   | `patrimonio_san_salvador.csv` |
| `descargar_man_made_san_salvador.py`   | `man_made`   | `infraestructura_san_salvador.csv` |

Junto a cada CSV queda un `.geojson` con los mismos registros, listo para abrir
en QGIS o en umap.

## Que trae cada archivo

Dentro de cada script hay dos listas de filtros:

- `FILTROS_POR_TAG`: la llave completa de la categoria (por ejemplo
  `nwr["shop"]`), mas las llaves vecinas con las que OpenStreetMap marca lo
  mismo con otro nombre (una farmacia es `amenity=pharmacy`, no `shop`). Es la
  consulta rapida, porque usa los indices de Overpass.
- `FILTROS_POR_NOMBRE`: busqueda por el texto del nombre, en espanol, para
  recuperar lo que esta mal etiquetado. Va en una consulta aparte porque es la
  lenta; si falla, no arrastra a la anterior.

Si un grupo no responde, el script lo avisa al final y de todos modos escribe
lo que si trajo.

## Notas por categoria

- **building**: baja los edificios con nombre y los que declaran un uso no
  residencial. Descargar *todos* los edificios del distrito (decenas de miles
  de casas sin nombre) hace que la consulta se pase del tiempo limite; el
  encabezado del archivo explica como forzarlo si de verdad se necesita.
- **place**: en El Salvador muchas colonias estan mapeadas como
  `landuse=residential` con nombre en vez de `place=*`, asi que tambien se
  piden esas.
- **cuisine** y **brand**: son llaves descriptivas mas que clases de lugar, asi
  que ademas de la llave se piden los locales que suelen llevarla (comida en un
  caso, cadenas y franquicias en el otro).
- **amenity**, **landuse**, **natural** y **man_made**: traen muchos elementos
  que no son negocios (bancas, paradas, arboles, postes). Para quedarse solo
  con lo que tiene nombre, basta filtrar la columna `nombre` del CSV.

## Columnas del CSV

`categoria`, `subcategoria`, `nombre`, `distrito`, `marca`, `operador`,
`latitud`, `longitud`, `direccion`, `ciudad`, `telefono`, `sitio_web`,
`horario`, `producto_o_cocina`, `osm_tipo`, `osm_id`, `url_osm`.

`subcategoria` guarda la llave y el valor que mejor describen al lugar
(`shop=bakery`, `amenity=restaurant`, ...), dando prioridad a la llave de la
categoria que se esta bajando.

Como las columnas son iguales en todos los archivos, los CSV se pueden unir:

```bash
head -1 datos/comercios_san_salvador.csv >  datos/todos.csv
tail -q -n +2 datos/*_san_salvador.csv   >> datos/todos.csv
```

## Otro distrito

En cada script, el bloque `DISTRITO` de arriba es lo unico que hay que cambiar:

```python
DISTRITO = "San Salvador"   # como queda escrito en el CSV y en los archivos
PATRON = "San Salvador"     # variantes del nombre en OpenStreetMap
```

---

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
