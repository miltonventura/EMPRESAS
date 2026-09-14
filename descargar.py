#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga restaurantes, inmobiliarias, residenciales y cafe desde OpenStreetMap
para la zona del volcan de San Salvador (El Salvador).

Uso:   pip install requests
       python3 descargar.py

Deja los archivos CSV y GeoJSON en la carpeta 'datos'.
Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import csv
import json
import os
import time

import requests

# ---------------------------------------------------------------- AJUSTES ---
LAT, LON = 13.7342, -89.2864   # crater El Boqueron, volcan de San Salvador
RADIO = 15000                  # metros a la redonda (15 km)
CARPETA = "datos"              # donde se guardan los resultados

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

CATEGORIAS = {
    "restaurantes": [
        'nwr["amenity"~"^(restaurant|fast_food|bar|pub|ice_cream|food_court)$"]',
        'nwr["shop"~"^(bakery|pastry|deli)$"]',
        'nwr["cuisine"~"pupusa|salvadoran",i]',
    ],
    "inmobiliarias": [
        'nwr["office"~"^(estate_agent|property_management|developer|construction_company)$"]',
        'nwr["shop"="estate_agent"]',
        'nwr["craft"="builder"]',
        'nwr["office"="architect"]',
        'nwr["name"~"inmobiliari|bienes ra|constructora|urbanizadora|desarrollos",i][!"highway"][!"landuse"][!"place"]',
    ],
    "residenciales": [
        'nwr["landuse"="residential"]["name"]',
        'nwr["place"~"^(neighbourhood|suburb|quarter|city_block)$"]["name"]',
        'nwr["building"~"^(apartments|residential)$"]["name"]',
        'nwr["name"~"residencial|condominio|apartament|urbanizaci|lotificaci|reparto |colonia ",i][!"highway"]',
    ],
    "cafe": [
        'nwr["amenity"="cafe"]',
        'nwr["shop"="coffee"]',
        'nwr["craft"="coffee_roastery"]',
        'nwr["crop"~"coffee|caf",i]',
        'nwr["produce"~"coffee|caf",i]',
        'nwr["product"~"coffee|caf",i]',
        'nwr["trees"~"coffee",i]',
        'nwr["name"~"caf[eé]|cafetal|beneficio|tostadur|finca ",i][!"highway"]',
    ],
}

COLUMNAS = ["categoria", "subcategoria", "nombre", "operador", "latitud", "longitud",
            "direccion", "ciudad", "telefono", "sitio_web", "horario",
            "producto_o_cocina", "osm_tipo", "osm_id", "url_osm"]

LLAVES_TIPO = ["amenity", "shop", "office", "craft", "landuse", "place",
               "building", "man_made", "crop", "produce", "product"]


def consultar(categoria):
    """Envia la consulta a Overpass y devuelve la lista de elementos."""
    filtros = "\n".join("  %s(around:%d,%s,%s);" % (f, RADIO, LAT, LON)
                        for f in CATEGORIAS[categoria])
    consulta = "[out:json][timeout:180];\n(\n%s\n);\nout tags center;" % filtros

    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=300,
                              headers={"User-Agent": "empresas-volcan/1.0"})
            if r.status_code == 200:
                return r.json().get("elements", [])
            print("   %s respondio %d" % (servidor, r.status_code))
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))
        espera = 5 * (2 ** intento)
        print("   reintentando en %d s..." % espera)
        time.sleep(espera)
    raise SystemExit("Overpass no respondio. Intenta de nuevo en unos minutos.")


def valor(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def fila(elemento, categoria):
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
    todas = {}

    for categoria in CATEGORIAS:
        print("Descargando %s..." % categoria)
        filas = [f for f in (fila(e, categoria) for e in consultar(categoria)) if f]
        filas.sort(key=lambda f: (f["nombre"] == "", f["nombre"].lower()))

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
        time.sleep(3)   # pausa amable con el servidor publico

    filas = sorted(todas.values(), key=lambda f: (f["categoria"], f["nombre"].lower()))
    guardar_csv(os.path.join(CARPETA, "empresas_todas.csv"), filas)

    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [f["longitud"], f["latitud"]]},
         "properties": f}
        for f in filas]}
    with open(os.path.join(CARPETA, "empresas.geojson"), "w", encoding="utf-8") as fh:
        json.dump(geojson, fh, ensure_ascii=False, indent=1)

    print("\nTotal sin duplicados: %d lugares" % len(filas))
    print("  %s/empresas_todas.csv" % CARPETA)
    print("  %s/empresas.geojson" % CARPETA)
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL.")


if __name__ == "__main__":
    main()
