#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga nombres y ubicaciones de empresas desde OpenStreetMap (API Overpass)
para la zona del volcan de San Salvador (Quezaltepeque), El Salvador.

Categorias: restaurantes, cafeterias, alimentos_bebidas, salones_eventos,
constructoras, fincas_cafe, beneficios_cafe, tostadurias_cafe y
parques_diversiones. Todas se descargan por defecto.

Salidas en la carpeta indicada con --salida:
  empresas_<categoria>.csv, empresas_todas.csv y empresas.geojson

Ejemplos:
  python3 overpass_empresas.py
  python3 overpass_empresas.py --radio 20000 --categorias restaurantes cafeterias
  python3 overpass_empresas.py --bbox 13.60 -89.45 13.90 -89.15
  python3 overpass_empresas.py --guardar-json crudo   # deja el JSON original
"""

import argparse
import csv
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Falta la libreria 'requests'. Instalala con:  pip install requests")

# Crater El Boqueron, volcan de San Salvador
VOLCAN_LAT = 13.7342
VOLCAN_LON = -89.2864
RADIO_M = 15000  # cubre Santa Tecla, Nejapa, Quezaltepeque, Colon y el poniente de San Salvador

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

CATEGORIAS = {
    "restaurantes": [
        'nwr["amenity"~"^(restaurant|fast_food|food_court|bbq)$"]',
        'nwr["cuisine"~"pupusa|salvadoran",i]',
        'nwr["name"~"restaurante|pupuser|comedor |marisquer|antojitos",i][!"highway"]',
    ],
    "cafeterias": [
        'nwr["amenity"="cafe"]',
        'nwr["shop"="coffee"]',
        'nwr["cuisine"~"coffee",i]',
        'nwr["name"~"cafeter|coffee",i][!"highway"]',
    ],
    "alimentos_bebidas": [
        'nwr["shop"~"^(bakery|pastry|butcher|deli|confectionery|greengrocer|seafood|dairy|alcohol|beverages|supermarket|wholesale|convenience|frozen_food|health_food|spices|tea|water)$"]',
        'nwr["craft"~"^(bakery|brewery|distillery|winery|confectionery|caterer|dairy|butcher)$"]',
        'nwr["amenity"~"^(bar|pub|biergarten|ice_cream)$"]',
        'nwr["industrial"~"^(food|brewery|slaughterhouse)$"]',
        'nwr["man_made"="works"]["product"~"food|drink|beverage|milk|dairy|meat|bread|sugar|beer|water",i]',
        'nwr["name"~"alimentos|bebidas|embotellador|cervecer|l[áa]cteos|panificadora|agroindustri|molinos? de|distribuidora de alimentos",i][!"highway"]',
    ],
    "salones_eventos": [
        'nwr["amenity"~"^(events_venue|conference_centre|exhibition_centre)$"]',
        'nwr["name"~"eventos|banquete|recepciones|convenciones|sal[oó]n social",i][!"highway"]',
    ],
    "constructoras": [
        'nwr["office"~"^(construction_company|developer)$"]',
        'nwr["craft"~"^(builder|carpenter|electrician|plumber)$"]',
        'nwr["office"="architect"]',
        'nwr["industrial"~"^(construction|cement|concrete)$"]',
        'nwr["name"~"constructora|construcciones|urbanizadora|ingenier[ií]a|desarrollos|prefabricad",i][!"highway"][!"landuse"][!"place"]',
    ],
    "fincas_cafe": [
        'nwr["crop"~"coffee|caf",i]',
        'nwr["produce"~"coffee|caf",i]',
        'nwr["trees"~"coffee",i]',
        'nwr["landuse"~"^(farmland|orchard)$"]["name"~"caf[eé]|cafetal|finca|hacienda",i]',
        'nwr["place"="farm"]',
        'nwr["name"~"cafetal|finca |hacienda ",i][!"highway"]',
    ],
    "beneficios_cafe": [
        'nwr["man_made"="works"]["product"~"coffee|caf",i]',
        'nwr["product"~"coffee|caf",i]["name"]',
        'nwr["name"~"beneficio|despulpad|trillo de caf",i][!"highway"]',
    ],
    "tostadurias_cafe": [
        'nwr["craft"="coffee_roastery"]',
        'nwr["shop"="coffee"]["name"~"tosta|torrefac",i]',
        'nwr["name"~"tostadur|tostado de caf|torrefac",i][!"highway"]',
    ],
    "parques_diversiones": [
        'nwr["tourism"="theme_park"]',
        'nwr["leisure"~"^(water_park|amusement_arcade)$"]',
        'nwr["attraction"]',
        'nwr["name"~"turicentro|parque acu|parque de divers|diversiones|mundo feliz",i][!"highway"]',
    ],
}

POR_DEFECTO = ['restaurantes', 'cafeterias', 'alimentos_bebidas', 'salones_eventos', 'constructoras', 'fincas_cafe', 'beneficios_cafe', 'tostadurias_cafe', 'parques_diversiones']

# Orden de prioridad para deducir la subcategoria de cada elemento
LLAVES_TIPO = ["amenity", "shop", "office", "craft", "landuse", "residential", "place",
               "man_made", "building", "tourism", "crop", "produce", "product"]

COLUMNAS = ["categoria", "subcategoria", "nombre", "marca", "operador",
            "latitud", "longitud", "osm_tipo", "osm_id", "url_osm",
            "direccion", "ciudad", "telefono", "correo", "sitio_web",
            "facebook", "horario", "producto_o_cocina", "descripcion"]


def construir_consulta(filtros, ambito, timeout):
    cuerpo = "\n".join("  {}{};".format(f, ambito) for f in filtros)
    return "[out:json][timeout:{}];\n(\n{}\n);\nout tags center;".format(timeout, cuerpo)


def ambito_desde_args(args):
    if args.bbox:
        sur, oeste, norte, este = args.bbox
        return "({},{},{},{})".format(sur, oeste, norte, este)
    return "(around:{},{},{})".format(args.radio, args.lat, args.lon)


def consultar(consulta, endpoints, intentos=4, espera=5):
    """Envia la consulta a Overpass, rotando de servidor y reintentando."""
    ultimo_error = None
    for intento in range(intentos):
        url = endpoints[intento % len(endpoints)]
        try:
            r = requests.post(url, data={"data": consulta}, timeout=300,
                              headers={"User-Agent": "empresas-volcan-sansalvador/1.0"})
            if r.status_code in (429, 504, 502, 503):
                ultimo_error = "{} respondio {}".format(url, r.status_code)
            else:
                r.raise_for_status()
                return r.json()
        except Exception as exc:  # red, timeout, json invalido
            ultimo_error = "{}: {}".format(url, exc)
        pausa = espera * (2 ** intento)
        print("   reintentando en {}s ({})".format(pausa, ultimo_error), file=sys.stderr)
        time.sleep(pausa)
    raise RuntimeError("Overpass no respondio. Ultimo error: {}".format(ultimo_error))


def coordenadas(elemento):
    if "lat" in elemento and "lon" in elemento:
        return elemento["lat"], elemento["lon"]
    centro = elemento.get("center") or {}
    return centro.get("lat"), centro.get("lon")


def subcategoria(tags):
    for llave in LLAVES_TIPO:
        if llave in tags:
            return "{}={}".format(llave, tags[llave])
    return "sin_clasificar"


def primero(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def direccion(tags):
    partes = []
    calle = primero(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    if calle:
        partes.append("{} {}".format(calle, numero).strip())
    elif numero:
        partes.append(numero)
    for llave in ("addr:suburb", "addr:neighbourhood", "addr:postcode"):
        if tags.get(llave):
            partes.append(tags[llave])
    return ", ".join(partes)


def a_fila(elemento, categoria):
    tags = elemento.get("tags", {})
    lat, lon = coordenadas(elemento)
    tipo, ident = elemento["type"], elemento["id"]
    return {
        "categoria": categoria,
        "subcategoria": subcategoria(tags),
        "nombre": primero(tags, "name", "name:es", "brand", "operator"),
        "marca": tags.get("brand", ""),
        "operador": tags.get("operator", ""),
        "latitud": lat,
        "longitud": lon,
        "osm_tipo": tipo,
        "osm_id": ident,
        "url_osm": "https://www.openstreetmap.org/{}/{}".format(tipo, ident),
        "direccion": direccion(tags),
        "ciudad": primero(tags, "addr:city", "addr:municipality", "is_in:city"),
        "telefono": primero(tags, "phone", "contact:phone", "contact:mobile"),
        "correo": primero(tags, "email", "contact:email"),
        "sitio_web": primero(tags, "website", "contact:website", "url"),
        "facebook": primero(tags, "contact:facebook", "facebook"),
        "horario": tags.get("opening_hours", ""),
        "producto_o_cocina": primero(tags, "cuisine", "crop", "product", "produce"),
        "descripcion": primero(tags, "description", "description:es"),
    }


def escribir_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS)
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({c: fila.get(c, "") for c in COLUMNAS})


def escribir_geojson(ruta, filas, tags_por_clave):
    features = []
    for fila in filas:
        if fila["latitud"] is None or fila["longitud"] is None:
            continue
        propiedades = dict(fila)
        propiedades["tags_osm"] = tags_por_clave.get((fila["osm_tipo"], fila["osm_id"]), {})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [fila["longitud"], fila["latitud"]]},
            "properties": propiedades,
        })
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features},
                  fh, ensure_ascii=False, indent=1)


def main():
    p = argparse.ArgumentParser(
        description="Descarga empresas de OpenStreetMap en la zona del volcan de San Salvador.")
    p.add_argument("--lat", type=float, default=VOLCAN_LAT, help="latitud del centro (crater El Boqueron)")
    p.add_argument("--lon", type=float, default=VOLCAN_LON, help="longitud del centro")
    p.add_argument("--radio", type=int, default=RADIO_M, help="radio en metros (por defecto 15000)")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("SUR", "OESTE", "NORTE", "ESTE"),
                   help="usar un rectangulo en vez del radio")
    p.add_argument("--categorias", nargs="+", choices=sorted(CATEGORIAS), default=POR_DEFECTO,
                   help="categorias a descargar (por defecto: %s)" % " ".join(POR_DEFECTO))
    p.add_argument("--salida", default="datos", help="carpeta de salida")
    p.add_argument("--endpoint", action="append", help="servidor Overpass (se puede repetir)")
    p.add_argument("--timeout", type=int, default=180, help="timeout que se le pide a Overpass")
    p.add_argument("--pausa", type=float, default=3, help="segundos de espera entre consultas")
    p.add_argument("--guardar-json", metavar="CARPETA", help="guardar la respuesta cruda de Overpass")
    p.add_argument("--solo-consulta", action="store_true", help="imprimir las consultas y salir")
    p.add_argument("--input-json", nargs=2, action="append", metavar=("CATEGORIA", "ARCHIVO"),
                   help="procesar un JSON ya descargado en vez de consultar la red")
    args = p.parse_args()

    endpoints = args.endpoint or ENDPOINTS
    ambito = ambito_desde_args(args)
    os.makedirs(args.salida, exist_ok=True)

    respuestas = []
    if args.input_json:
        for categoria, ruta in args.input_json:
            with open(ruta, encoding="utf-8") as fh:
                respuestas.append((categoria, json.load(fh)))
    else:
        for categoria in args.categorias:
            consulta = construir_consulta(CATEGORIAS[categoria], ambito, args.timeout)
            if args.solo_consulta:
                print("/* {} */\n{}\n".format(categoria, consulta))
                continue
            print("Consultando '{}' ...".format(categoria))
            datos = consultar(consulta, endpoints)
            if args.guardar_json:
                os.makedirs(args.guardar_json, exist_ok=True)
                with open(os.path.join(args.guardar_json, categoria + ".json"),
                          "w", encoding="utf-8") as fh:
                    json.dump(datos, fh, ensure_ascii=False)
            respuestas.append((categoria, datos))
            time.sleep(args.pausa)
        if args.solo_consulta:
            return 0

    combinadas = {}   # (tipo, id) -> fila
    tags_por_clave = {}
    total_por_categoria = {}

    for categoria, datos in respuestas:
        filas = []
        for elemento in datos.get("elements", []):
            if elemento.get("type") not in ("node", "way", "relation"):
                continue
            fila = a_fila(elemento, categoria)
            if fila["latitud"] is None:
                continue
            filas.append(fila)
            clave = (fila["osm_tipo"], fila["osm_id"])
            tags_por_clave[clave] = elemento.get("tags", {})
            if clave in combinadas:
                previas = combinadas[clave]["categoria"].split("|")
                if categoria not in previas:
                    combinadas[clave]["categoria"] += "|" + categoria
            else:
                combinadas[clave] = dict(fila)

        con_nombre = sum(1 for f in filas if f["nombre"])
        total_por_categoria[categoria] = (len(filas), con_nombre)
        ruta = os.path.join(args.salida, "empresas_{}.csv".format(categoria))
        escribir_csv(ruta, sorted(filas, key=lambda f: (f["nombre"] == "", f["nombre"].lower())))
        print("  {:<14} {:>5} lugares ({} con nombre)  ->  {}".format(
            categoria, len(filas), con_nombre, ruta))

    todas = sorted(combinadas.values(), key=lambda f: (f["categoria"], f["nombre"].lower()))
    csv_todas = os.path.join(args.salida, "empresas_todas.csv")
    geojson = os.path.join(args.salida, "empresas.geojson")
    escribir_csv(csv_todas, todas)
    escribir_geojson(geojson, todas, tags_por_clave)

    print("\nTotal sin duplicados: {} lugares".format(len(todas)))
    print("  {}\n  {}".format(csv_todas, geojson))
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL "
          "(https://www.openstreetmap.org/copyright)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
