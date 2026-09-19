#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga las edificaciones con nombre o uso declarado (building=* de
OpenStreetMap) del distrito de SAN SALVADOR, El Salvador.

Trae dos cosas: todo edificio que tenga nombre, y todo edificio cuyo valor
de building=* declare un uso no residencial (comercial, oficinas, industria,
bodega, hotel, hospital, escuela, iglesia, gobierno, estadio, terminal,
etc.). Asi se evita descargar las decenas de miles de casas sin nombre del
distrito, que harian que la consulta se pase del tiempo limite.

Si de verdad necesitas TODOS los edificios, deja FILTROS_POR_TAG con una
sola linea: nwr["building"]  -- y prepara paciencia, porque la consulta
puede tardar varios minutos o no completarse en los servidores publicos.

Este archivo baja UNA SOLA categoria de UN SOLO distrito. Para otro distrito
solo hay que cambiar el bloque DISTRITO de mas abajo; todo lo demas queda
igual. Para otra categoria, usa el archivo descargar_<categoria>_*.py que le
corresponde.

Uso:   pip install requests
       python3 descargar_building_san_salvador.py

Deja en la carpeta 'datos':
    edificaciones_san_salvador.csv
    edificaciones_san_salvador.geojson

Los CSV de todas las categorias y distritos tienen las mismas columnas, asi
que al final se pueden unir con:
    head -1 datos/edificaciones_san_salvador.csv >  datos/todos.csv
    tail -q -n +2 datos/*_san_salvador.csv       >> datos/todos.csv

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import collections
import csv
import json
import os
import time

import requests

# --------------------------------------------------------------- DISTRITO ---
# Unico distrito que baja este archivo.
#   NOMBRE  es como quedara escrito en el CSV y en el nombre de los archivos.
#   PATRON  admite las variantes de escritura con las que el nombre puede
#           estar en OpenStreetMap (con o sin tilde, nombre antiguo, etc.).
DISTRITO = "San Salvador"
PATRON = "San Salvador"

# ---------------------------------------------------------------- AJUSTES ---
CARPETA = "datos"   # donde se guardan los resultados

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Filtros de la categoria building=*. Primero se pide la llave completa, asi
# entran de una sola vez todos sus valores. Luego se agregan redes de
# seguridad: llaves vecinas que en OpenStreetMap marcan lo mismo con otro
# nombre, y una busqueda por nombre para lo mal etiquetado.
FILTROS_POR_TAG = [
    'nwr["building"]["name"]',
    'nwr["building"~"^(commercial|retail|office|industrial|warehouse|supermarket|kiosk|hotel|hostel|motel|hospital|clinic|school|university|college|kindergarten|church|cathedral|chapel|mosque|temple|synagogue|religious|civic|government|public|stadium|sports_hall|sports_centre|grandstand|train_station|transportation|fire_station|police|museum|manufacture|factory|service|hangar|farm|barn|greenhouse|parking|garages|ruins|construction)$"]',
    'nwr["building:use"]',
    'nwr["building:levels"]["name"]',
]

# Esta categoria no lleva filtro por nombre: el primer filtro de arriba ya
# pide nwr["building"]["name"], que trae todo edificio con nombre usando el
# indice de Overpass, sin el costo de revisar texto elemento por elemento.
FILTROS_POR_NOMBRE = [

]

CATEGORIA = "edificaciones"

COLUMNAS = ["categoria", "subcategoria", "nombre", "distrito", "marca", "operador",
            "latitud", "longitud", "direccion", "ciudad", "telefono",
            "sitio_web", "horario", "producto_o_cocina",
            "osm_tipo", "osm_id", "url_osm"]

# Orden en que se busca la llave que mejor describe a cada lugar. Para esta
# categoria manda building; las demas solo entran si el elemento no la trae.
LLAVES_TIPO = ["building", "shop", "amenity", "healthcare", "office",
               "craft", "industrial", "tourism", "leisure", "sport",
               "club", "historic", "man_made", "landuse", "natural",
               "place", "cuisine", "brand"]

# Rectangulo que contiene a El Salvador; acota la busqueda de la frontera
# para que no aparezcan homonimos de otros paises.
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"

# El proxy de entrada de los servidores publicos corta alrededor de los 180 s,
# asi que pedir mas es contraproducente: en vez de un aviso limpio de Overpass
# ("Query timed out"), que este script sabe reintentar, la conexion muere con
# un 504 seco. Tampoco se fija maxsize: reservar memoria de mas obliga al
# despachador a esperar un bloque libre grande, y esa espera sola agota el
# tiempo del gateway.
TIMEOUT_CONSULTA = 180          # segundos que se le piden a Overpass
PAUSA_ENTRE_CONSULTAS = 3       # segundos de cortesia con el servidor publico
PASO_REJILLA = 0.005            # ~550 m; agrupa los segmentos de frontera


def sin_tildes(texto):
    return texto.translate(str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN"))


BASE = sin_tildes(DISTRITO).lower().replace(" ", "_")


# -------------------------------------------------------------- OVERPASS ---
def consultar(consulta, etiqueta, obligatorio=True):
    """Envia una consulta a Overpass y devuelve la respuesta ya convertida.

    Si los reintentos se agotan devuelve None, salvo que sea obligatorio.
    """
    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=300,
                              headers={"User-Agent": "empresas-sv/1.0"})
            if r.status_code == 200:
                datos = r.json()
                # Overpass a veces contesta 200 pero con un aviso de error en
                # el cuerpo (por ejemplo "runtime error: Query timed out").
                # Sin esta revision el CSV saldria vacio sin explicacion.
                aviso = datos.get("remark", "")
                if "error" not in aviso.lower() and "timed out" not in aviso.lower():
                    return datos
                print("   %s aviso: %s" % (servidor, " ".join(aviso.split())[:150]))
            else:
                print("   %s respondio %d" % (servidor, r.status_code))
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))
        espera = 10 * (2 ** intento)
        print("   reintentando %s en %d s..." % (etiqueta, espera))
        time.sleep(espera)
    if obligatorio:
        raise SystemExit("Overpass no respondio (%s). Intenta de nuevo mas tarde." % etiqueta)
    return None


def consulta_de_filtros(area_id, filtros):
    """Arma la consulta apuntando al area ya conocida del distrito.

    Se usa area(<id>) en vez de volver a buscar la frontera con
    rel(bbox)[name~...] + map_to_area: esa reconstruccion escanea todas las
    relaciones administrativas del pais y se repetiria en cada consulta,
    aunque la frontera ya se descargo al inicio.
    """
    cuerpo = "\n".join("  %s(area.zona);" % f for f in filtros)
    return ("[out:json][timeout:%d];\narea(%d)->.zona;\n(\n%s\n);\nout tags center;"
            % (TIMEOUT_CONSULTA, area_id, cuerpo))


# -------------------------------------------------------------- FRONTERA ---
def descargar_frontera():
    """Baja la frontera del distrito (y la guarda en cache).

    La cache es la misma para todas las categorias, asi que la frontera solo
    se descarga con el primer archivo que se corra.
    """
    cache = os.path.join(CARPETA, "_frontera_%s.json" % BASE)
    if os.path.exists(cache):
        print("Frontera de %s: usando la copia guardada." % DISTRITO)
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    print("Descargando la frontera de %s..." % DISTRITO)
    consulta = (
        '[out:json][timeout:%d];\n'
        'rel(%s)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]'
        '["name"~"^(%s)$"];\nout geom;'
    ) % (TIMEOUT_CONSULTA, BBOX_PAIS, PATRON)
    datos = consultar(consulta, "frontera de %s" % DISTRITO)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)
    return datos


def area_y_poligono(datos):
    """Devuelve (id de area, rejilla de segmentos) a partir de la frontera.

    En Overpass el area de una relacion es 3600000000 + el id de la relacion.
    """
    for relacion in datos.get("elements", []):
        if relacion.get("type") != "relation":
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
            return 3600000000 + relacion["id"], dict(rejilla)
    raise SystemExit(
        "No se encontro la frontera de %s en OpenStreetMap. Revisa el PATRON." % DISTRITO)


def cae_dentro(lat, lon, rejilla):
    """Dice si el punto cae dentro de la frontera del distrito."""
    cruces = 0
    for lat1, lon1, lat2, lon2 in rejilla.get(int(lat / PASO_REJILLA), ()):
        if (lat1 > lat) != (lat2 > lat):
            corte = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < corte:
                cruces += 1
    return bool(cruces % 2)


# ---------------------------------------------------------------- SALIDA ---
def valor(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def fila(elemento):
    tags = elemento.get("tags", {})
    centro = elemento.get("center", {})
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None

    subcat = "sin_clasificar"
    for llave in LLAVES_TIPO:
        if tags.get(llave):
            subcat = "%s=%s" % (llave, tags[llave])
            break

    calle = valor(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    return {
        "categoria": CATEGORIA,
        "subcategoria": subcat,
        "nombre": valor(tags, "name", "name:es", "brand", "operator"),
        "distrito": DISTRITO,
        "marca": valor(tags, "brand", "brand:short"),
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


def main():
    os.makedirs(CARPETA, exist_ok=True)

    area_id, rejilla = area_y_poligono(descargar_frontera())
    print("  area(%d)\n" % area_id)

    # Dos consultas: primero los filtros por tag, que usan los indices de
    # Overpass y vuelan; despues el de nombre, que es el lento.
    vistos, elementos, fallaron = set(), [], []
    grupos = [("tags", FILTROS_POR_TAG), ("nombres", FILTROS_POR_NOMBRE)]
    for grupo, filtros in grupos:
        if not filtros:
            continue
        print("Descargando %s de %s (%s)..." % (CATEGORIA, DISTRITO, grupo))
        datos = consultar(consulta_de_filtros(area_id, filtros),
                          "%s / %s" % (DISTRITO, grupo), obligatorio=False)
        if datos is None:
            print("   sin respuesta, se omite este grupo")
            fallaron.append(grupo)
            continue

        devueltos = datos.get("elements", [])
        nuevos = 0
        for elemento in devueltos:
            clave = (elemento["type"], elemento["id"])
            if clave in vistos:
                continue        # ya vino en el otro grupo
            vistos.add(clave)
            elementos.append(elemento)
            nuevos += 1
        print("   %d lugares, %d nuevos (van %d)" % (len(devueltos), nuevos, len(elementos)))
        time.sleep(PAUSA_ENTRE_CONSULTAS)

    if fallaron:
        print("\nOJO, grupo(s) sin datos: %s" % ", ".join(fallaron))
        print("Los resultados de abajo estan incompletos. Vuelve a correrlo mas tarde.")

    filas = [f for f in (fila(e) for e in elementos) if f]
    filas.sort(key=lambda f: (f["nombre"] == "", f["nombre"].lower()))

    ruta_csv = os.path.join(CARPETA, "%s_%s.csv" % (CATEGORIA, BASE))
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)

    ruta_geo = os.path.join(CARPETA, "%s_%s.geojson" % (CATEGORIA, BASE))
    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [f["longitud"], f["latitud"]]},
         "properties": f}
        for f in filas]}
    with open(ruta_geo, "w", encoding="utf-8") as fh:
        json.dump(geojson, fh, ensure_ascii=False, indent=1)

    # Resumen
    fuera = sum(1 for f in filas if not cae_dentro(f["latitud"], f["longitud"], rejilla))
    print("\n%s: %d lugares (%d con nombre)" % (DISTRITO, len(filas),
                                                sum(1 for f in filas if f["nombre"])))
    if fuera:
        print("  %d quedaron fuera del poligono (suelen ser lugares sobre la frontera)" % fuera)
    print("\n  Los 12 tipos mas frecuentes:")
    for tipo, cuantos in collections.Counter(f["subcategoria"] for f in filas).most_common(12):
        print("    %-32s %5d" % (tipo, cuantos))
    print("\n  %s\n  %s" % (ruta_csv, ruta_geo))
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL.")


if __name__ == "__main__":
    main()
