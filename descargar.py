#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga empresas desde OpenStreetMap para 28 distritos de El Salvador
(AMSS y la franja costera de La Libertad).

Categorias: restaurantes, cafeterias, alimentos y bebidas, salones de eventos,
constructoras, fincas de cafe, beneficios de cafe, tostadurias y parques de
diversiones.

Uso:   pip install requests
       python3 descargar.py

Deja los archivos CSV y GeoJSON en la carpeta 'datos'. Cada resultado queda
etiquetado con el distrito en el que cae.

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import collections
import csv
import json
import os
import re
import time

import requests

# ---------------------------------------------------------------- AJUSTES ---
CARPETA = "datos"   # donde se guardan los resultados

# Distritos a consultar. Cada patron admite las variantes de escritura con las
# que el nombre puede estar en OpenStreetMap (con o sin tilde, etc.).
DISTRITOS = [
    ("San Salvador",          "San Salvador"),
    ("Ayutuxtepeque",         "Ayutuxtepeque"),
    ("Mejicanos",             "Mejicanos"),
    ("Cuscatancingo",         "Cuscatancingo"),
    ("Ciudad Delgado",        "(Ciudad )?Delgado"),
    ("Apopa",                 "Apopa"),
    ("Nejapa",                "Nejapa"),
    ("Ilopango",              "Ilopango"),
    ("San Martin",            "San Mart[ií]n"),
    ("Soyapango",             "Soyapango"),
    ("Tonacatepeque",         "Tonacatepeque"),
    ("San Marcos",            "San Marcos"),
    ("Panchimalco",           "Panchimalco"),
    ("Rosario de Mora",       "Rosario de Mora"),
    ("Santiago Texacuangos",  "Santiago Texacuangos"),
    ("Santo Tomas",           "Santo Tom[áa]s"),
    ("Antiguo Cuscatlan",     "Antiguo Cuscatl[áa]n"),
    ("Huizucar",              "Huiz[úu]car"),
    ("Nuevo Cuscatlan",       "Nuevo Cuscatl[áa]n"),
    ("San Jose Villanueva",   "San Jos[eé] Villa ?[Nn]ueva"),
    ("Zaragoza",              "Zaragoza"),
    ("Chiltiupan",            "Chiltiup[áa]n"),
    ("Jicalapa",              "Jicalapa"),
    ("La Libertad",           "La Libertad"),
    ("Tamanique",             "Tamanique"),
    ("Teotepeque",            "Teotepeque"),
    ("Santa Tecla",           "Santa Tecla|Nueva San Salvador"),
    ("Comasagua",             "Comasagua"),
]

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

CATEGORIAS = {
    # Comida servida en mesa
    "restaurantes": [
        'nwr["amenity"~"^(restaurant|fast_food|food_court|bbq)$"]',
        'nwr["cuisine"~"pupusa|salvadoran",i]',
        'nwr["name"~"restaurante|pupuser|comedor |marisquer|antojitos",i][!"highway"]',
    ],
    # Cafeterias y tiendas de cafe
    "cafeterias": [
        'nwr["amenity"="cafe"]',
        'nwr["shop"="coffee"]',
        'nwr["cuisine"~"coffee",i]',
        'nwr["name"~"cafeter|coffee",i][!"highway"]',
    ],
    # Produccion, distribucion y venta de alimentos y bebidas
    "alimentos_bebidas": [
        'nwr["shop"~"^(bakery|pastry|butcher|deli|confectionery|greengrocer|seafood|dairy|alcohol|beverages|supermarket|wholesale|convenience|frozen_food|health_food|spices|tea|water)$"]',
        'nwr["craft"~"^(bakery|brewery|distillery|winery|confectionery|caterer|dairy|butcher)$"]',
        'nwr["amenity"~"^(bar|pub|biergarten|ice_cream)$"]',
        'nwr["industrial"~"^(food|brewery|slaughterhouse)$"]',
        'nwr["man_made"="works"]["product"~"food|drink|beverage|milk|dairy|meat|bread|sugar|beer|water",i]',
        'nwr["name"~"alimentos|bebidas|embotellador|cervecer|l[áa]cteos|panificadora|agroindustri|molinos? de|distribuidora de alimentos",i][!"highway"]',
    ],
    # Salones para eventos, banquetes y convenciones
    "salones_eventos": [
        'nwr["amenity"~"^(events_venue|conference_centre|exhibition_centre)$"]',
        'nwr["name"~"eventos|banquete|recepciones|convenciones|sal[oó]n social",i][!"highway"]',
    ],
    # Empresas constructoras
    "constructoras": [
        'nwr["office"~"^(construction_company|developer)$"]',
        'nwr["craft"~"^(builder|carpenter|electrician|plumber)$"]',
        'nwr["office"="architect"]',
        'nwr["industrial"~"^(construction|cement|concrete)$"]',
        'nwr["name"~"constructora|construcciones|urbanizadora|ingenier[ií]a|desarrollos|prefabricad",i][!"highway"][!"landuse"][!"place"]',
    ],
    # Fincas y cafetales
    "fincas_cafe": [
        'nwr["crop"~"coffee|caf",i]',
        'nwr["produce"~"coffee|caf",i]',
        'nwr["trees"~"coffee",i]',
        'nwr["landuse"~"^(farmland|orchard)$"]["name"~"caf[eé]|cafetal|finca|hacienda",i]',
        'nwr["place"="farm"]',
        'nwr["name"~"cafetal|finca |hacienda ",i][!"highway"]',
    ],
    # Beneficios (procesamiento del cafe)
    "beneficios_cafe": [
        'nwr["man_made"="works"]["product"~"coffee|caf",i]',
        'nwr["product"~"coffee|caf",i]["name"]',
        'nwr["name"~"beneficio|despulpad|trillo de caf",i][!"highway"]',
    ],
    # Tostadurias y torrefactoras
    "tostadurias_cafe": [
        'nwr["craft"="coffee_roastery"]',
        'nwr["shop"="coffee"]["name"~"tosta|torrefac",i]',
        'nwr["name"~"tostadur|tostado de caf|torrefac",i][!"highway"]',
    ],
    # Parques de diversiones, acuaticos y turicentros
    "parques_diversiones": [
        'nwr["tourism"="theme_park"]',
        'nwr["leisure"~"^(water_park|amusement_arcade)$"]',
        'nwr["attraction"]',
        'nwr["name"~"turicentro|parque acu|parque de divers|diversiones|mundo feliz",i][!"highway"]',
    ],
}

COLUMNAS = ["categoria", "subcategoria", "nombre", "distrito", "operador",
            "latitud", "longitud", "direccion", "ciudad", "telefono",
            "sitio_web", "horario", "producto_o_cocina",
            "osm_tipo", "osm_id", "url_osm"]

LLAVES_TIPO = ["amenity", "shop", "office", "craft", "tourism", "leisure",
               "landuse", "place", "industrial", "man_made", "attraction",
               "building", "crop", "produce", "product"]

# Rectangulo que contiene a El Salvador; acota la busqueda de los limites
# administrativos para que no aparezcan homonimos de otros paises.
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"

# Selecciona los limites de los distritos y los convierte en area de busqueda.
SELECCION = (
    'rel(%s)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]'
    '["name"~"^(%s)$"]->.d;'
) % (BBOX_PAIS, "|".join(patron for _, patron in DISTRITOS))

TIMEOUT_CONSULTA = 600   # segundos que se le piden a Overpass
PASO_REJILLA = 0.005     # ~550 m; agrupa los segmentos de frontera por latitud


# ------------------------------------------------------------- OVERPASS ---
def consultar(consulta, etiqueta):
    """Envia una consulta a Overpass y devuelve la respuesta ya convertida."""
    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=900,
                              headers={"User-Agent": "empresas-sv/1.0"})
            if r.status_code == 200:
                return r.json()
            print("   %s respondio %d" % (servidor, r.status_code))
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))
        espera = 10 * (2 ** intento)
        print("   reintentando %s en %d s..." % (etiqueta, espera))
        time.sleep(espera)
    raise SystemExit("Overpass no respondio (%s). Intenta de nuevo mas tarde." % etiqueta)


def consulta_de_categoria(categoria):
    filtros = "\n".join("  %s(area.zona);" % f for f in CATEGORIAS[categoria])
    return ("[out:json][timeout:%d];\n%s\n.d map_to_area ->.zona;\n(\n%s\n);\n"
            "out tags center;" % (TIMEOUT_CONSULTA, SELECCION, filtros))


# ------------------------------------------------------------ DISTRITOS ---
def descargar_distritos():
    """Baja las fronteras de los distritos (y las guarda en cache)."""
    cache = os.path.join(CARPETA, "_distritos.json")
    if os.path.exists(cache):
        print("Fronteras de distritos: usando la copia guardada.")
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    print("Descargando las fronteras de los %d distritos..." % len(DISTRITOS))
    consulta = ("[out:json][timeout:%d];\n%s\n.d out geom;" % (TIMEOUT_CONSULTA, SELECCION))
    datos = consultar(consulta, "fronteras")
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)
    return datos


def armar_poligonos(datos):
    """Convierte las relaciones de frontera en segmentos agrupados por latitud."""
    poligonos = {}
    for relacion in datos.get("elements", []):
        nombre = relacion.get("tags", {}).get("name", "")
        if not nombre or nombre in poligonos:
            continue
        rejilla = collections.defaultdict(list)
        for miembro in relacion.get("members", []):
            puntos = miembro.get("geometry") or []
            for a, b in zip(puntos, puntos[1:]):
                if a["lat"] == b["lat"]:
                    continue   # los segmentos horizontales no cruzan el rayo
                segmento = (a["lat"], a["lon"], b["lat"], b["lon"])
                desde = int(min(a["lat"], b["lat"]) / PASO_REJILLA)
                hasta = int(max(a["lat"], b["lat"]) / PASO_REJILLA)
                for banda in range(desde, hasta + 1):
                    rejilla[banda].append(segmento)
        if rejilla:
            poligonos[nombre] = dict(rejilla)
    return poligonos


def distrito_de(lat, lon, poligonos):
    """Devuelve el distrito que contiene al punto, o '' si cae fuera."""
    banda = int(lat / PASO_REJILLA)
    for nombre, rejilla in poligonos.items():
        cruces = 0
        for lat1, lon1, lat2, lon2 in rejilla.get(banda, ()):
            if (lat1 > lat) != (lat2 > lat):
                corte = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
                if lon < corte:
                    cruces += 1
        if cruces % 2:
            return nombre
    return ""


# -------------------------------------------------------------- SALIDA ---
def valor(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def fila(elemento, categoria, poligonos):
    tags = elemento.get("tags", {})
    centro = elemento.get("center", {})
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None

    subcat = "sin_clasificar"
    for llave in LLAVES_TIPO:
        if llave in tags:
            subcat = "%s=%s" % (llave, tags[llave])
            break

    calle = valor(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    return {
        "categoria": categoria,
        "subcategoria": subcat,
        "nombre": valor(tags, "name", "name:es", "brand", "operator"),
        "distrito": distrito_de(lat, lon, poligonos),
        "operador": valor(tags, "operator", "brand"),
        "latitud": lat,
        "longitud": lon,
        "direccion": ("%s %s" % (calle, numero)).strip(),
        "ciudad": valor(tags, "addr:city", "addr:municipality"),
        "telefono": valor(tags, "phone", "contact:phone", "contact:mobile"),
        "sitio_web": valor(tags, "website", "contact:website", "contact:facebook"),
        "horario": tags.get("opening_hours", ""),
        "producto_o_cocina": valor(tags, "cuisine", "crop", "produce", "product"),
        "osm_tipo": elemento["type"],
        "osm_id": elemento["id"],
        "url_osm": "https://www.openstreetmap.org/%s/%s" % (elemento["type"], elemento["id"]),
    }


def guardar_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)


def main():
    os.makedirs(CARPETA, exist_ok=True)

    poligonos = armar_poligonos(descargar_distritos())
    print("  %d distritos encontrados" % len(poligonos))
    faltan = [n for n, patron in DISTRITOS
              if not any(re.fullmatch(patron, nombre, re.IGNORECASE)
                         for nombre in poligonos)]
    if faltan:
        print("  OJO, sin frontera en OSM: %s" % ", ".join(faltan))
    print()

    todas = {}
    for categoria in CATEGORIAS:
        print("Descargando %s..." % categoria)
        datos = consultar(consulta_de_categoria(categoria), categoria)
        filas = [f for f in (fila(e, categoria, poligonos)
                             for e in datos.get("elements", [])) if f]
        filas.sort(key=lambda f: (f["distrito"], f["nombre"] == "", f["nombre"].lower()))

        ruta = os.path.join(CARPETA, "empresas_%s.csv" % categoria)
        guardar_csv(ruta, filas)
        print("  %d lugares (%d con nombre)  ->  %s"
              % (len(filas), sum(1 for f in filas if f["nombre"]), ruta))

        for f in filas:
            clave = (f["osm_tipo"], f["osm_id"])
            if clave in todas:
                if categoria not in todas[clave]["categoria"].split("|"):
                    todas[clave]["categoria"] += "|" + categoria
            else:
                todas[clave] = dict(f)
        time.sleep(5)   # pausa amable con el servidor publico

    filas = sorted(todas.values(),
                   key=lambda f: (f["distrito"], f["categoria"], f["nombre"].lower()))
    guardar_csv(os.path.join(CARPETA, "empresas_todas.csv"), filas)

    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [f["longitud"], f["latitud"]]},
         "properties": f}
        for f in filas]}
    with open(os.path.join(CARPETA, "empresas.geojson"), "w", encoding="utf-8") as fh:
        json.dump(geojson, fh, ensure_ascii=False, indent=1)

    print("\nTotal sin duplicados: %d lugares" % len(filas))
    por_distrito = collections.Counter(f["distrito"] or "(fuera de los distritos)"
                                       for f in filas)
    for nombre, cuantos in por_distrito.most_common():
        print("  %-24s %5d" % (nombre, cuantos))
    print("\n  %s/empresas_todas.csv" % CARPETA)
    print("  %s/empresas.geojson" % CARPETA)
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL.")


if __name__ == "__main__":
    main()
