# EMPRESAS — datos de empresas del volcán de San Salvador (OpenStreetMap)

Descarga **nombres y ubicaciones** desde la **API Overpass** de OpenStreetMap para
la zona del volcán de San Salvador (Quezaltepeque), El Salvador.

Zona por defecto: círculo de **15 km** alrededor del cráter El Boquerón
(`13.7342, -89.2864`). Cubre Santa Tecla, Nejapa, Quezaltepeque, Colón,
Antiguo Cuscatlán y el poniente de San Salvador.

## Las nueve categorías

| Categoría | Qué recoge |
|---|---|
| `restaurantes` | Restaurantes, comida rápida, pupuserías, comedores, marisquerías |
| `cafeterias` | Cafeterías y tiendas de café |
| `alimentos_bebidas` | Producción, distribución y venta: panaderías, carnicerías, lácteos, embotelladoras, cervecerías, supermercados, mayoristas, bares |
| `salones_eventos` | Salones de eventos, banquetes, recepciones y centros de convenciones |
| `constructoras` | Constructoras, urbanizadoras, ingenierías, oficinas de arquitectura, prefabricados |
| `fincas_cafe` | Cafetales y fincas: `crop=coffee`, `produce=coffee`, y fincas y haciendas con nombre |
| `beneficios_cafe` | Beneficios y despulpadoras de café |
| `tostadurias_cafe` | Tostadurías y torrefactoras |
| `parques_diversiones` | Parques temáticos, acuáticos, turicentros y salas de juegos |

Cada categoría busca **por etiqueta formal de OSM y también por nombre**, porque en
El Salvador mucho está mapeado sin la etiqueta correcta. Los hallazgos que salieron
solo por el nombre se marcan como `sin_clasificar` en la columna `subcategoria`;
revísalos, ahí es donde se cuela el ruido.

Un mismo lugar puede caer en dos categorías (una finca que además tiene beneficio).
En los archivos por categoría aparece en las dos; en `empresas_todas.csv` sale una
sola vez, con la columna `categoria` uniéndolas con `|`.

## Opción A — script (deja CSV + GeoJSON)

```bash
pip install -r requirements.txt
python3 overpass_empresas.py
```

Genera en `datos/`:

- un CSV por categoría: `empresas_restaurantes.csv`, `empresas_cafeterias.csv`, etc.

- `empresas_todas.csv` — todo junto, sin duplicados (si un lugar cae en dos
  categorías, la columna `categoria` las une con `|`)
- `empresas.geojson` — para QGIS, Google My Maps, Kepler.gl o geojson.io

Columnas: categoría, subcategoría, nombre, marca, operador, latitud, longitud,
tipo e id de OSM, enlace al elemento, dirección, ciudad, teléfono, correo,
sitio web, facebook, horario, producto/cocina y descripción.

### Variantes útiles

```bash
# Radio más amplio (25 km)
python3 overpass_empresas.py --radio 25000

# Solo una categoría
python3 overpass_empresas.py --categorias cafe

# Sumar el resto del agro
python3 overpass_empresas.py --categorias restaurantes inmobiliarias residenciales cafe agricultura

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
   (o `inmobiliarias`, `residenciales`, `cafe`, `agricultura`)
3. **Ejecutar** → **Exportar** → *GeoJSON*, *CSV* o *GPX*

## Opción C — QGIS

Complemento **QuickOSM**: pestaña *Consulta* y pegar los mismos `.overpassql`,
con la extensión centrada en el volcán.

## Notas importantes

- **La cobertura depende de lo que la comunidad haya mapeado.** Los restaurantes
  están bastante completos en Santa Tecla, Escalón y San Salvador; las colonias y
  residenciales también salen bien porque se mapean como polígonos. En cambio las
  **inmobiliarias como empresa están muy sub-mapeadas** (espera decenas, no
  cientos), y en café saldrán sobre todo polígonos de cafetal, muchos sin razón
  social.
- Para un padrón *formal* de empresas complementa con el Directorio de Unidades
  Económicas (BCR/DIGESTYC) o el Registro de Comercio del CNR; OSM no es un
  registro mercantil.
- Datos © colaboradores de OpenStreetMap, licencia **ODbL**: al publicar o
  redistribuir hay que atribuir y compartir bajo la misma licencia.
  <https://www.openstreetmap.org/copyright>
- Sé considerado con la API pública de Overpass: no lances la descarga en bucle.

## Script de un solo archivo

`descargar.py` es la versión copia-y-pega: sin argumentos ni opciones, se corre con
`python3 descargar.py`.

**Su área de búsqueda son 28 distritos** (el AMSS completo más la franja costera de
La Libertad), no el círculo de 15 km: San Salvador, Ayutuxtepeque, Mejicanos,
Cuscatancingo, Ciudad Delgado, Apopa, Nejapa, Ilopango, San Martín, Soyapango,
Tonacatepeque, San Marcos, Panchimalco, Rosario de Mora, Santiago Texacuangos,
Santo Tomás, Antiguo Cuscatlán, Huizúcar, Nuevo Cuscatlán, San José Villanueva,
Zaragoza, Chiltiupán, Jicalapa, La Libertad, Tamanique, Teotepeque, Santa Tecla
y Comasagua. La lista se edita en `DISTRITOS`, al inicio del archivo.

Usa las fronteras administrativas reales de OpenStreetMap, avisa si algún distrito
no aparece en OSM, y **etiqueta cada resultado con el distrito donde cae** (columna
`distrito`). Las fronteras se guardan en `datos/_distritos.json` para no volver a
descargarlas; bórralo si cambias la lista de distritos.

`overpass_empresas.py` sigue trabajando por radio y con opciones de línea de comandos.
