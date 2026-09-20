# EMPRESAS — descarga de OpenStreetMap por distrito y categoria

Scripts para consultar y descargar los datos de OpenStreetMap de 8 distritos de
El Salvador, **un archivo por categoria y por distrito** (18 x 8 = 144
archivos).

Todos comparten la misma estructura: bajan la frontera del distrito (y la
guardan en cache), consultan Overpass dentro de esa area y dejan los resultados
en la carpeta `datos/`, en CSV y GeoJSON, con las mismas columnas en todos los
casos.

## Uso

```bash
pip install requests
cd san_salvador
python3 descargar_shop_san_salvador.py
```

Cada archivo se corre por su cuenta y tarda alrededor de un minuto. Conviene
correrlos parado dentro de la carpeta del distrito: los resultados quedan en
`<distrito>/datos/` y la frontera se descarga una sola vez, porque el primero
que se corra deja `datos/_frontera_<distrito>.json` y los otros 17 la
reutilizan.

## Distritos

| Carpeta | Distrito | Como puede estar escrito en OpenStreetMap |
|---|---|---|
| `san_salvador/`   | San Salvador   | San Salvador |
| `santa_tecla/`    | Santa Tecla    | Santa Tecla **o** Nueva San Salvador |
| `quezaltepeque/`  | Quezaltepeque  | Quezaltepeque |
| `san_juan_opico/` | San Juan Opico | San Juan Opico **o** Opico |
| `colon/`          | Colón          | Colón **o** Colon |
| `mejicanos/`      | Mejicanos      | Mejicanos |
| `ayutuxtepeque/`  | Ayutuxtepeque  | Ayutuxtepeque |
| `nejapa/`         | Nejapa         | Nejapa |

Cada script busca la frontera por nombre dentro de un recuadro (`BBOX_BUSQUEDA`)
ajustado a los alrededores de su distrito, no a todo el pais: **Quezaltepeque** y
**Colón** son tambien municipios de Guatemala y Honduras, y con un recuadro
grande Overpass podria devolver la frontera equivocada. Si el nombre llega a
coincidir con mas de una frontera, el script lo avisa y muestra las candidatas
antes de seguir.

## Categorias

Las 18 categorias estan en las 8 carpetas, con el nombre del distrito al final
del archivo. Por ejemplo, en `santa_tecla/` el de comercios es
`descargar_shop_santa_tecla.py`.

| Archivo | Llave de OSM | Salida en `datos/` |
|---|---|---|
| `descargar_shop_*.py`       | `shop`       | `comercios_*.csv` |
| `descargar_office_*.py`     | `office`     | `oficinas_*.csv` |
| `descargar_craft_*.py`      | `craft`      | `oficios_*.csv` |
| `descargar_brand_*.py`      | `brand`      | `marcas_*.csv` |
| `descargar_industrial_*.py` | `industrial` | `industrias_*.csv` |
| `descargar_amenity_*.py`    | `amenity`    | `servicios_*.csv` |
| `descargar_leisure_*.py`    | `leisure`    | `recreacion_*.csv` |
| `descargar_tourism_*.py`    | `tourism`    | `turismo_*.csv` |
| `descargar_sport_*.py`      | `sport`      | `deportes_*.csv` |
| `descargar_cuisine_*.py`    | `cuisine`    | `gastronomia_*.csv` |
| `descargar_club_*.py`       | `club`       | `clubes_*.csv` |
| `descargar_healthcare_*.py` | `healthcare` | `salud_*.csv` |
| `descargar_building_*.py`   | `building`   | `edificaciones_*.csv` |
| `descargar_landuse_*.py`    | `landuse`    | `usos_de_suelo_*.csv` |
| `descargar_place_*.py`      | `place`      | `lugares_*.csv` |
| `descargar_natural_*.py`    | `natural`    | `naturaleza_*.csv` |
| `descargar_historic_*.py`   | `historic`   | `patrimonio_*.csv` |
| `descargar_man_made_*.py`   | `man_made`   | `infraestructura_*.csv` |

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
  residencial. Descargar *todos* los edificios (decenas de miles de casas sin
  nombre) hace que la consulta se pase del tiempo limite; el encabezado del
  archivo explica como forzarlo si de verdad se necesita.
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

Como las columnas son iguales en todos los archivos, los CSV se pueden unir.
Dentro de un distrito:

```bash
head -1 datos/comercios_san_salvador.csv >  datos/todos.csv
tail -q -n +2 datos/*_san_salvador.csv   >> datos/todos.csv
```

O los 8 distritos de una vez, desde la raiz del repositorio:

```bash
head -1 san_salvador/datos/comercios_san_salvador.csv >  todos.csv
tail -q -n +2 */datos/*_*.csv | grep -v '^categoria,' >> todos.csv
```

## Otro distrito

Para agregar uno nuevo, se copia cualquier carpeta y se cambian las tres lineas
de arriba de cada script:

```python
DISTRITO = "San Salvador"                      # como queda escrito en el CSV
PATRON = "San Salvador"                        # variantes del nombre en OSM
BBOX_BUSQUEDA = "13.55,-89.40,13.90,-89.05"    # sur,oeste,norte,este
```

---

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
