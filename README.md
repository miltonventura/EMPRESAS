# EMPRESAS — Extracción de datos de OpenStreetMap (San Salvador y La Libertad)

Búsqueda de empresas y lugares a partir de OpenStreetMap.

`extraer_osm.py` consulta la **Overpass API** de OpenStreetMap y genera **un archivo Excel
por categoría** con todos los lugares registrados en los **departamentos de San Salvador y
La Libertad** (El Salvador), incluyendo todos sus municipios y distritos.

## Instalación

```bash
pip install -r requirements.txt      # openpyxl (obligatorio) y shapely (opcional)
python extraer_osm.py --autoprueba   # verifica la instalación sin usar la red
```

Requiere Python 3.8 o superior. `shapely` es opcional: si no está instalada, el script
usa un algoritmo interno de *point-in-polygon* (funciona igual, solo más lento).

## Uso

```bash
python extraer_osm.py                                   # las 21 categorías, ambos departamentos
python extraer_osm.py --categorias shop office craft    # solo algunas categorías
python extraer_osm.py --departamentos "San Salvador"    # un solo departamento
python extraer_osm.py --formato ambos                   # genera .xlsx y .csv
python extraer_osm.py --listar-categorias               # ver categorías y subcategorías
python extraer_osm.py --categorias building --pausa 4   # ser más amable con el servidor
python extraer_osm.py --diagnostico                     # antes de descargar: ¿cuánto hay?
```

### Empiece con `--diagnostico`

Antes de la primera extracción conviene correr `--diagnostico`. No descarga datos: verifica
el servidor, muestra los límites administrativos que encontró (con los `admin_level` reales
de OSM y cuáles se usarán como municipio y distrito) y, con consultas `out count`, dice
**cuántos elementos traerá cada categoría**, el tiempo aproximado y el espacio en disco.
Así sabe qué esperar y detecta cualquier problema en minutos, no en horas.

Opciones principales:

| Opción | Para qué sirve |
|---|---|
| `--categorias`, `-c` | Categorías a extraer (por omisión, todas) |
| `--departamentos`, `-d` | Departamentos (por omisión: San Salvador y La Libertad) |
| `--salida`, `-o` | Carpeta de salida (por omisión `salida/`) |
| `--formato`, `-f` | `excel` (por omisión), `csv` o `ambos` |
| `--cache` / `--sin-cache` | Carpeta de caché de respuestas / no usar caché |
| `--endpoint` | Servidor Overpass preferido |
| `--timeout`, `--pausa`, `--reintentos` | Control de la carga sobre el servidor |
| `--division N` | Forzar división de las consultas en N×N mosaicos |
| `--sin-admin` | No asignar municipio/distrito (más rápido) |
| `--diagnostico` | Verifica servidor y límites, y cuenta elementos sin descargarlos |
| `--autoprueba` | Pruebas internas sin red |

## Categorías (21 archivos de salida)

| Grupo | Categorías (llave OSM) |
|---|---|
| Negocios y comercio | `shop`, `office`, `craft`, `brand`, `industrial` |
| Servicios y equipamientos | `amenity` |
| Ocio, turismo y deporte | `leisure`, `tourism`, `sport`, `cuisine`, `club` |
| Salud | `healthcare` |
| Territorio y edificios | `building`, `landuse`, `place`, `natural`, `historic`, `man_made` |
| Transporte y emergencias | `public_transport`, `aeroway`, `emergency` |

El script consulta **todos los valores** de cada llave (por ejemplo `shop=*`, no una lista
cerrada), así que trae también las subcategorías poco comunes. Además incluye un catálogo
de **1,091 subcategorías traducidas al español** (201 solo de `shop`); un valor que no esté
en el catálogo se exporta igual, con su valor OSM en `subcategoria` y una versión legible
en `subcategoria_es`.

`public_transport` también recoge `highway=bus_stop`, `amenity=bus_station` y
`amenity=ferry_terminal`, que es como se mapean en la práctica las paradas y terminales.

## Qué contiene cada archivo

Hojas de cada `.xlsx`:

* **Datos** — un registro por lugar (filtros automáticos y encabezado fijo).
* **Resumen_subcategoria** — conteo por subcategoría.
* **Resumen_territorio** — conteo por departamento / municipio / distrito.
* **Ficha_tecnica** — filtros usados, totales, fecha y fuente.

Además se genera `00_RESUMEN_GENERAL.xlsx` con los totales por categoría, los registros por
municipio y la lista de límites administrativos utilizados.

Columnas de la hoja *Datos* (53 en total, según la categoría):

`categoria`, `categoria_es`, `grupo`, `subcategoria`, `subcategoria_es`, `nombre`,
`nombre_alterno`, `marca`, `operador`, `latitud`, `longitud`, `departamento`, `municipio`,
`distrito`, `unidades_administrativas`, `direccion`, `calle`, `numero`, `colonia_barrio`, `ciudad`, `codigo_postal`,
`telefono`, `celular_whatsapp`, `correo`, `sitio_web`, `facebook`, `horario`, `cocina`,
`deporte`, `religion`, `accesibilidad`, `internet`, `acepta_tarjeta`, `niveles_edificio`,
`capacidad`, `wikidata`, `codigo_referencia`, `descripcion`, `fuente_osm`, `osm_tipo`,
`osm_id`, `osm_url`, `fecha_consulta`, columnas `tag_*` propias de cada categoría y
`todas_las_etiquetas` (JSON con **todas** las etiquetas OSM del elemento, para que no se
pierda ningún dato).

## Cómo funciona

1. Descarga de OSM el límite de El Salvador, luego los departamentos solicitados
   (`admin_level=4`) y sus municipios/distritos (`admin_level` 5 a 9).
2. Por cada categoría y departamento consulta Overpass con `nwr[llave](area)` y
   `out tags center`, de modo que nodos, vías y relaciones traen un punto representativo.
3. Las categorías grandes (`building`, `landuse`, `natural`, `man_made`, …) se dividen en
   mosaicos; si el servidor se satura, el mosaico se subdivide en 4 y se reintenta.
4. A cada elemento se le asigna municipio y distrito por geometría (*point-in-polygon*), y la
   columna `unidades_administrativas` guarda **todos** los niveles que lo contienen, por si la
   división territorial de OSM cambia o tiene niveles intermedios.
   Los puntos exactamente sobre un límite cuentan como dentro, y los que quedan hasta
   ~300 m fuera de todo polígono se asignan al límite más cercano.
5. Un elemento que cruza el límite entre los dos departamentos se guarda **una sola vez**,
   en el departamento que contiene su punto.

Las respuestas se guardan en `cache_osm/`, así que volver a correr el script (o continuar
después de interrumpirlo con Ctrl-C) no vuelve a consultar lo ya descargado.

## Tiempos y consideraciones

* Overpass es un servicio comunitario gratuito y con cuotas. El script consulta de forma
  secuencial, con pausa entre consultas y reintentos con espera creciente.
* Una corrida completa de las 21 categorías toma **entre una y varias horas**, casi todo en
  `building` y `landuse`. Empiece con `-c shop office craft amenity` para tener resultados
  pronto.
* Si necesita la base completa con frecuencia, conviene montar una instancia propia de
  Overpass o usar los extractos de Geofabrik para Centroamérica y pasar `--endpoint`.

## Fuente y licencia de los datos

Los datos provienen de **OpenStreetMap**, © colaboradores de OpenStreetMap, bajo licencia
**ODbL 1.0**. Si publica o redistribuye estos datos debe mantener la atribución
«© OpenStreetMap contributors». La cobertura depende de lo que la comunidad haya mapeado:
es muy buena en el área metropolitana de San Salvador y más dispersa en zonas rurales.
