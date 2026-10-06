# EMPRESAS
Búsqueda de empresas

## Apopa — descarga de OpenStreetMap por categoria

La carpeta `apopa/` tiene 18 scripts, uno por categoria de OpenStreetMap, para
el distrito de Apopa (San Salvador Norte). Siguen la misma estructura que los
de los otros distritos (`descargar_<categoria>_<distrito>.py`).

```bash
pip install requests
cd apopa
python3 correr_todo_apopa.py      # corre las 18 categorias y las une en datos/todos_apopa.csv
```

Los resultados quedan en `apopa/datos/` como `<categoria>_apopa.csv` y
`<categoria>_apopa.geojson`. El primer script que se corra descarga la frontera
del distrito y la guarda en `datos/_frontera_apopa.json`; los otros 17 la
reutilizan.

| Archivo | Llave de OSM | Salida en `datos/` |
|---|---|---|
| `descargar_shop_apopa.py`       | `shop`       | `comercios_apopa.csv` |
| `descargar_office_apopa.py`     | `office`     | `oficinas_apopa.csv` |
| `descargar_craft_apopa.py`      | `craft`      | `oficios_apopa.csv` |
| `descargar_brand_apopa.py`      | `brand`      | `marcas_apopa.csv` |
| `descargar_industrial_apopa.py` | `industrial` | `industrias_apopa.csv` |
| `descargar_amenity_apopa.py`    | `amenity`    | `servicios_apopa.csv` |
| `descargar_leisure_apopa.py`    | `leisure`    | `recreacion_apopa.csv` |
| `descargar_tourism_apopa.py`    | `tourism`    | `turismo_apopa.csv` |
| `descargar_sport_apopa.py`      | `sport`      | `deportes_apopa.csv` |
| `descargar_cuisine_apopa.py`    | `cuisine`    | `gastronomia_apopa.csv` |
| `descargar_club_apopa.py`       | `club`       | `clubes_apopa.csv` |
| `descargar_healthcare_apopa.py` | `healthcare` | `salud_apopa.csv` |
| `descargar_building_apopa.py`   | `building`   | `edificaciones_apopa.csv` |
| `descargar_landuse_apopa.py`    | `landuse`    | `usos_de_suelo_apopa.csv` |
| `descargar_place_apopa.py`      | `place`      | `lugares_apopa.csv` |
| `descargar_natural_apopa.py`    | `natural`    | `naturaleza_apopa.csv` |
| `descargar_historic_apopa.py`   | `historic`   | `patrimonio_apopa.csv` |
| `descargar_man_made_apopa.py`   | `man_made`   | `infraestructura_apopa.csv` |

Configuracion del distrito (las tres lineas de arriba de cada script):

```python
DISTRITO = "Apopa"
PATRON = "Apopa"
BBOX_BUSQUEDA = "13.70,-89.30,13.95,-89.05"    # sur,oeste,norte,este
```

Para unir todas las categorias en un solo CSV:

```bash
cd apopa
head -1 datos/comercios_apopa.csv >  datos/todos.csv
tail -q -n +2 datos/*_apopa.csv   >> datos/todos.csv
```

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.

## Antiguo Cuscatlán — descarga de OpenStreetMap por categoria

La carpeta `antiguo_cuscatlan/` tiene 18 scripts, uno por categoria de OpenStreetMap, para
el distrito de Antiguo Cuscatlán (La Libertad Este). Siguen la misma estructura que los
de los otros distritos (`descargar_<categoria>_<distrito>.py`).

```bash
pip install requests
cd antiguo_cuscatlan
python3 correr_todo_antiguo_cuscatlan.py      # corre las 18 categorias y las une en datos/todos_antiguo_cuscatlan.csv
```

Los resultados quedan en `antiguo_cuscatlan/datos/` como `<categoria>_antiguo_cuscatlan.csv` y
`<categoria>_antiguo_cuscatlan.geojson`. El primer script que se corra descarga la frontera
del distrito y la guarda en `datos/_frontera_antiguo_cuscatlan.json`; los otros 17 la
reutilizan.

| Archivo | Llave de OSM | Salida en `datos/` |
|---|---|---|
| `descargar_shop_antiguo_cuscatlan.py`       | `shop`       | `comercios_antiguo_cuscatlan.csv` |
| `descargar_office_antiguo_cuscatlan.py`     | `office`     | `oficinas_antiguo_cuscatlan.csv` |
| `descargar_craft_antiguo_cuscatlan.py`      | `craft`      | `oficios_antiguo_cuscatlan.csv` |
| `descargar_brand_antiguo_cuscatlan.py`      | `brand`      | `marcas_antiguo_cuscatlan.csv` |
| `descargar_industrial_antiguo_cuscatlan.py` | `industrial` | `industrias_antiguo_cuscatlan.csv` |
| `descargar_amenity_antiguo_cuscatlan.py`    | `amenity`    | `servicios_antiguo_cuscatlan.csv` |
| `descargar_leisure_antiguo_cuscatlan.py`    | `leisure`    | `recreacion_antiguo_cuscatlan.csv` |
| `descargar_tourism_antiguo_cuscatlan.py`    | `tourism`    | `turismo_antiguo_cuscatlan.csv` |
| `descargar_sport_antiguo_cuscatlan.py`      | `sport`      | `deportes_antiguo_cuscatlan.csv` |
| `descargar_cuisine_antiguo_cuscatlan.py`    | `cuisine`    | `gastronomia_antiguo_cuscatlan.csv` |
| `descargar_club_antiguo_cuscatlan.py`       | `club`       | `clubes_antiguo_cuscatlan.csv` |
| `descargar_healthcare_antiguo_cuscatlan.py` | `healthcare` | `salud_antiguo_cuscatlan.csv` |
| `descargar_building_antiguo_cuscatlan.py`   | `building`   | `edificaciones_antiguo_cuscatlan.csv` |
| `descargar_landuse_antiguo_cuscatlan.py`    | `landuse`    | `usos_de_suelo_antiguo_cuscatlan.csv` |
| `descargar_place_antiguo_cuscatlan.py`      | `place`      | `lugares_antiguo_cuscatlan.csv` |
| `descargar_natural_antiguo_cuscatlan.py`    | `natural`    | `naturaleza_antiguo_cuscatlan.csv` |
| `descargar_historic_antiguo_cuscatlan.py`   | `historic`   | `patrimonio_antiguo_cuscatlan.csv` |
| `descargar_man_made_antiguo_cuscatlan.py`   | `man_made`   | `infraestructura_antiguo_cuscatlan.csv` |

Configuracion del distrito (las tres lineas de arriba de cada script):

```python
DISTRITO = "Antiguo Cuscatlán"
PATRON = "Antiguo Cuscatl[áa]n"           # con o sin tilde
BBOX_BUSQUEDA = "13.60,-89.35,13.75,-89.15"    # sur,oeste,norte,este
```

Para unir todas las categorias en un solo CSV:

```bash
cd antiguo_cuscatlan
head -1 datos/comercios_antiguo_cuscatlan.csv >  datos/todos.csv
tail -q -n +2 datos/*_antiguo_cuscatlan.csv   >> datos/todos.csv
```

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
