# EMPRESAS — datos de empresas del volcán de San Salvador (OpenStreetMap)

Descarga **nombres y ubicaciones** de negocios en la zona del volcán de San Salvador
(Quezaltepeque), El Salvador, usando la **API Overpass** de OpenStreetMap.

Zona por defecto: círculo de **15 km** alrededor del cráter El Boquerón
(`13.7342, -89.2864`). Cubre Santa Tecla, Nejapa, Quezaltepeque, Colón,
Antiguo Cuscatlán y el poniente de San Salvador.

## Categorías

| Categoría | Qué trae (etiquetas OSM) |
|---|---|
| `restaurantes` | `amenity=restaurant/fast_food/cafe/bar/pub/ice_cream/food_court`, más panaderías, cafés de venta, supermercados y tiendas de alimentos |
| `inmobiliarias` | `office=estate_agent/property_management/developer/construction_company`, `shop=estate_agent`, `craft=builder`, `office=architect` |
| `agricultura` | `shop=agrarian/farm/garden_centre`, `craft=agricultural_engines`, fincas y cafetales con nombre (`landuse=farmland/orchard/...`, `crop=*`), `place=farm`, beneficios de café (`product=coffee`) |
| `residenciales` | *(opcional, no se baja por defecto)* urbanizaciones y residenciales con nombre |

## Opción A — script (recomendado, deja CSV + GeoJSON)

```bash
pip install -r requirements.txt
python3 overpass_empresas.py
```

Genera en `datos/`:

- `empresas_restaurantes.csv`, `empresas_inmobiliarias.csv`, `empresas_agricultura.csv`
- `empresas_todas.csv` — todo junto, sin duplicados
- `empresas.geojson` — para abrir en QGIS, Google My Maps, Kepler.gl o geojson.io

Columnas: categoría, subcategoría, nombre, marca, operador, latitud, longitud,
tipo e id de OSM, enlace al elemento, dirección, ciudad, teléfono, correo,
sitio web, facebook, horario, producto/cocina y descripción.

### Variantes útiles

```bash
# Radio más amplio (25 km)
python3 overpass_empresas.py --radio 25000

# Solo dos categorías, incluyendo residenciales
python3 overpass_empresas.py --categorias restaurantes residenciales

# Rectángulo en vez de círculo: sur oeste norte este
python3 overpass_empresas.py --bbox 13.60 -89.45 13.90 -89.15

# Otro centro (por ejemplo el casco de Santa Tecla)
python3 overpass_empresas.py --lat 13.6731 --lon -89.2797 --radio 8000

# Ver las consultas sin descargar nada
python3 overpass_empresas.py --solo-consulta

# Guardar también la respuesta original de Overpass
python3 overpass_empresas.py --guardar-json datos/crudo
```

El script reintenta con espera creciente y rota entre tres servidores Overpass
(`overpass-api.de`, `kumi.systems`, `private.coffee`) si uno está saturado.

## Opción B — sin programar, en el navegador

1. Abrir <https://overpass-turbo.eu>
2. Pegar el contenido de `consultas/restaurantes.overpassql`
   (o `inmobiliarias`, `agricultura`, `residenciales`)
3. **Ejecutar** → **Exportar** → *GeoJSON*, *CSV* o *GPX*

## Opción C — QGIS

Complemento **QuickOSM**: pestaña *Consulta rápida*, llave `amenity` valor
`restaurant`, extensión = lienzo del mapa centrado en el volcán. O bien
*Consulta* y pegar los mismos `.overpassql`.

## Notas importantes

- **La cobertura depende de lo que la comunidad haya mapeado.** En El Salvador
  los restaurantes están bastante completos en Santa Tecla y San Salvador;
  inmobiliarias y agroservicios están sub-representados. Los resultados sin
  nombre (`nombre` vacío) son lugares mapeados sin razón social.
- Para un registro *oficial* de empresas conviene complementar con el
  Directorio de Unidades Económicas (DIGESTYC/BCR) o el Registro de Comercio (CNR);
  OSM no es un registro mercantil.
- Datos © colaboradores de OpenStreetMap, licencia **ODbL**: si publicas o
  redistribuyes, hay que dar atribución y compartir bajo la misma licencia.
  <https://www.openstreetmap.org/copyright>
- Sé considerado con la API pública de Overpass: no lances la descarga en bucle.
