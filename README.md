# EMPRESAS — registros de OpenStreetMap de San Salvador y La Libertad

Descarga registros de **OpenStreetMap** para los departamentos de **San Salvador**
y **La Libertad** (El Salvador), con todos sus municipios y distritos, usando la
API Overpass.

## Qué trae

No son filtros hechos a mano: el script baja **todos los valores** de cada
etiqueta de OSM pedida. Un archivo por grupo:

| Archivo | Etiqueta OSM | Contenido |
|---|---|---|
| `osm_comercios.csv` | `shop=*` | supermercados, tiendas, centros comerciales, panaderías, ferreterías, farmacias, repuestos, papelerías, agroservicios… (~150 valores) |
| `osm_oficinas.csv` | `office=*` | empresas, abogados, notarías, contadores, aseguradoras, inmobiliarias, TI, ONG, constructoras, coworking |
| `osm_talleres.csv` | `craft=*` | carpintería, electricista, plomería, herrería, sastrería, imprenta, rotulación, cervecería artesanal |
| `osm_industria.csv` | `industrial=*` | fábricas, bodegas, refinerías, aserraderos, rastros |
| `osm_servicios.csv` | `amenity=*` | restaurantes, cafeterías, bancos, cajeros, hospitales, clínicas, escuelas, gasolineras, mercados, iglesias, alcaldías, funerarias… |
| `osm_ocio.csv` | `leisure=*` | parques, canchas, gimnasios, piscinas, estadios, marinas |
| `osm_turismo.csv` | `tourism=*` | hoteles, moteles, hostales, museos, miradores, parques de diversiones |
| `osm_clubes.csv` | `club=*` | clubes deportivos, sociales, culturales, náuticos |
| `osm_uso_del_suelo.csv` | `landuse=*` | zonas comerciales, industriales, residenciales, cultivos, bosques, canteras |
| `osm_lugares.csv` | `place=*` | ciudades, pueblos, cantones, caseríos, colonias, barrios |
| `osm_naturales.csv` | `natural=*` | playas, volcanes, cerros, manglares, manantiales |
| `osm_historicos.csv` | `historic=*` | monumentos, ruinas, sitios arqueológicos |
| `osm_infraestructura.csv` | `man_made=*` | torres, antenas, tanques de agua, muelles, faros, silos |
| `osm_edificios.csv` | `building=*` | edificios (ver la nota de volumen más abajo) |

Más `osm_todo.csv` con todo junto sin duplicados, y `osm_todo.geojson` para mapas.

**La marca, el tipo de cocina y el deporte no son grupos aparte**, porque en OSM
no son categorías sino atributos de otra cosa: un `brand=Pollo Campero` siempre
va encima de un `amenity=fast_food`. Viajan como las columnas `marca`, `cocina`
y `deporte` de cada registro.

## Columnas

`grupo`, `clave`, `valor`, `etiqueta_es`, `nombre`, `marca`, `operador`,
`departamento`, `municipio`, `distrito`, `latitud`, `longitud`, `direccion`,
`ciudad`, `telefono`, `correo`, `sitio_web`, `horario`, `cocina`, `deporte`,
`tipo_club`, `osm_tipo`, `osm_id`, `url_osm`.

- `valor` es el valor crudo de OSM (`supermarket`); `etiqueta_es` es su
  traducción (`supermercado`), para que el CSV se pueda leer y filtrar en español.
- Si un lugar cae en dos grupos (un supermercado que además tiene farmacia),
  en `osm_todo.csv` aparece una sola vez con los grupos unidos por `|`.
- `departamento`, `municipio` y `distrito` se calculan geométricamente: se bajan
  los polígonos administrativos y se ubica cada punto dentro de ellos.

## Uso

```bash
pip install requests
python3 descargar.py
```

### Ajustes, al inicio del archivo

- `DEPARTAMENTOS` — la lista de departamentos. El script descubre solo sus
  municipios y distritos; no hay que enumerarlos.
- `GRUPOS` — comenta con `#` la línea de un grupo que no quieras bajar.
- `EDIFICIOS_COMPLETOS` — ver abajo.
- `CARPETA` — dónde se guardan los resultados.

Los límites administrativos se guardan en `datos/_limites.json` para no volver a
descargarlos. **Bórralo si cambias `DEPARTAMENTOS`.**

## Volumen: lee esto antes de correrlo

Esto ya no es una consulta pequeña. Dos departamentos enteros y catorce
etiquetas completas pueden ser **cientos de miles de registros** y **una o
varias horas** de descarga.

- **Los edificios son el grupo más grande con diferencia.** Con
  `EDIFICIOS_COMPLETOS = False` (el valor por defecto) se traen solo los
  edificios con nombre o de uso no residencial, que es lo útil para un censo de
  negocios. En `True` se trae cada casa mapeada: decenas o cientos de miles de
  polígonos que Excel ya no abre cómodamente.
- **El script parte el área solo.** Primero intenta la consulta completa; si el
  servidor no puede, la reparte por municipios, y si tampoco, por distritos. Los
  edificios arrancan directamente distrito por distrito.
- **El GeoJSON combinado se omite** si el total pasa de 200 000 registros
  (`LIMITE_GEOJSON`); los CSV siempre se escriben.
- Es un servidor público y gratuito: no lo corras en bucle.

## Sin programar, en el navegador

En `consultas/` hay un `.overpassql` por grupo, ya delimitado a los dos
departamentos. Se pegan en <https://overpass-turbo.eu> → **Ejecutar** →
**Exportar**. Para las etiquetas grandes conviene reducir antes el área.

## Notas

- **La cobertura es la que tenga OpenStreetMap.** Comercios y servicios están
  razonablemente completos en San Salvador, Antiguo Cuscatlán y Santa Tecla, y
  escasos en el resto. Oficinas, talleres e industria están sub-mapeados en todo
  el país. OSM no es un registro mercantil: para un padrón formal, cruza con el
  Registro de Comercio (CNR) o el directorio de unidades económicas del BCR.
- Datos © colaboradores de OpenStreetMap, licencia **ODbL**: al publicar o
  redistribuir hay que atribuir y compartir bajo la misma licencia.
  <https://www.openstreetmap.org/copyright>
