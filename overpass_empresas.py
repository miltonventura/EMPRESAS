#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga nombres y ubicaciones de empresas desde OpenStreetMap (API Overpass)
para la zona del volcan de San Salvador (Quezaltepeque), El Salvador.

Categorias incluidas:
  - restaurantes  : restaurantes, comida rapida, cafeterias, bares, pupuserias...
  - inmobiliarias : agentes y administradoras de bienes raices, constructoras
  - agricultura   : fincas, cafetales, viveros, agroservicios, beneficios de cafe
  - residenciales : (opcional) urbanizaciones y residenciales con nombre

Salidas en la carpeta indicada con --salida:
  empresas_<categoria>.csv, empresas_todas.csv y empresas.geojson

Ejemplos:
  python3 overpass_empresas.py
  python3 overpass_empresas.py --radio 20000 --categorias restaurantes agricultura
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
        'nwr["amenity"~"^(restaurant|fast_food|cafe|bar|pub|ice_cream|food_court|biergarten)$"]',
        'nwr["shop"~"^(bakery|coffee|deli|pastry|butcher|greengrocer|convenience|supermarket)$"]',
    ],
    "inmobiliarias": [
        'nwr["office"~"^(estate_agent|property_management|developer|construction_company)$"]',
        'nwr["shop"="estate_agent"]',
        'nwr["craft"="builder"]',
        'nwr["office"="architect"]',
    ],
    "agricultura": [
        'nwr["shop"~"^(agrarian|farm|garden_centre)$"]',
        'nwr["craft"~"^(agricultural_engines|distillery|winery)$"]',
        'nwr["landuse"~"^(farmland|orchard|vineyard|greenhouse_horticulture|plant_nursery|meadow)$"]["name"]',
        'nwr["place"="farm"]',
        'nwr["crop"]',
        'nwr["product"~"coffee|caf",i]["name"]',
        'nwr["man_made"="works"]["name"]',
    ],
    # No se descarga por defecto: son poligonos de urbanizaciones, no empresas.
    "residenciales": [
        'nwr["landuse"="residential"]["name"]',
        'nwr["building"="apartments"]["name"]',
    ],
}

POR_DEFECTO = ["restaurantes", "inmobiliarias", "agricultura"]

# Orden de prioridad para deducir la subcategoria de cada elemento
LLAVES_TIPO = ["amenity", "shop", "office", "craft", "landuse", "place",
               "man_made", "building", "tourism", "industrial"]

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
    return ""


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
