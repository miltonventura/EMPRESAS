#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga empresas desde OpenStreetMap para 28 distritos de El Salvador
(AMSS y la franja costera de La Libertad).

Categoria: oficinas y empresas (office=* de OpenStreetMap). Incluye
empresas, gobierno, abogados, notarias, contadores, aseguradoras,
inmobiliarias, tecnologia, telecomunicaciones, agencias de empleo,
arquitectos, ingenieria, consultoria, publicidad, ONG, fundaciones,
partidos politicos, embajadas, logistica, courier, constructoras y
coworking.

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

# Cada categoria corresponde a una llave raiz de OpenStreetMap. Primero se pide
# la llave completa (asi entran los ~150 valores de shop=*, todos los office=*,
# etc.) y luego se agregan redes de seguridad: llaves vecinas que en la practica
# marcan el mismo tipo de negocio, y busquedas por nombre en espanol para los
# lugares que quedaron mal etiquetados.
CATEGORIAS = {
    # ---- office=* : oficinas y empresas -----------------------------------
    # Primero se pide la llave completa, asi entran de una sola vez todos los
    # valores de office=* (company, government, lawyer, notary, accountant,
    # insurance, estate_agent, it, telecommunication, employment_agency,
    # architect, engineer, consulting, advertising_agency, ngo, foundation,
    # political_party, diplomatic, logistics, courier, construction_company,
    # coworking, etc.). Luego se agregan redes de seguridad: llaves vecinas
    # que marcan lo mismo y busquedas por nombre para lo mal etiquetado.
    "oficinas": [
        'nwr["office"]',
        # Sedes de gobierno y representaciones que OSM marca con amenity.
        'nwr["amenity"~"^(townhall|courthouse|post_office|embassy|public_building|prosecutor)$"]',
        'nwr["diplomatic"]',
        'nwr["building"="office"]["name"]',
        # Rotulos tipicos de oficinas y empresas en El Salvador.
        'nwr["name"~"bufete|abogad|jur[ií]dic|notar[ií]a|despacho|contador|contadur[ií]a|auditor|aseguradora|seguros |correduri|inmobiliaria|bienes ra[ií]ces|consultor|asesor[ií]a|publicidad|mercadeo|agencia de|corredora|corporaci[óo]n|sociedad an[óo]nima|importadora|exportadora|comercializadora|constructora|urbanizadora|ingenier[ií]a|arquitect|tecnolog[ií]a|inform[áa]tica|software|sistemas |soluciones |desarrolladora|telecomunicaciones|empleo|recursos humanos|bolsa de trabajo|fundaci[óo]n|asociaci[óo]n|cooperativa|sindicato|partido |ministerio de|viceministerio|alcald[ií]a|embajada|consulado|c[áa]mara de|gremial|courier|encomiendas|paqueter|log[ií]stica|aduanal|coworking|call center|outsourcing",i][!"highway"][!"landuse"][!"place"][!"boundary"]',
    ],
}

# Llave de OSM que mejor describe cada categoria; se usa para nombrar la
# subcategoria de cada resultado (por ejemplo shop=hardware, office=lawyer).
LLAVE_PRINCIPAL = {
    "oficinas": ["office", "diplomatic", "amenity", "building"],
}

COLUMNAS = ["categoria", "subcategoria", "nombre", "distrito", "marca", "operador",
            "latitud", "longitud", "direccion", "ciudad", "telefono",
            "sitio_web", "horario", "producto_o_cocina",
            "osm_tipo", "osm_id", "url_osm"]

LLAVES_TIPO = ["shop", "office", "craft", "industrial", "amenity", "healthcare",
               "tourism", "leisure", "man_made", "landuse", "place",
               "attraction", "building", "crop", "produce", "product", "brand"]

# Rectangulo que contiene a El Salvador; acota la busqueda de los limites
# administrativos para que no aparezcan homonimos de otros paises.
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"

TIMEOUT_CONSULTA = 900          # segundos que se le piden a Overpass
MAXSIZE_CONSULTA = 1073741824   # 1 GB; las categorias completas son grandes
PASO_REJILLA = 0.005            # ~550 m; agrupa los segmentos de frontera por latitud


def seleccion(patrones=None):
    """Selecciona los limites de los distritos indicados (todos por omision)."""
    if patrones is None:
        patrones = [patron for _, patron in DISTRITOS]
    return ('rel(%s)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]'
            '["name"~"^(%s)$"]->.d;') % (BBOX_PAIS, "|".join(patrones))


# ------------------------------------------------------------- OVERPASS ---
def consultar(consulta, etiqueta, obligatorio=True):
    """Envia una consulta a Overpass y devuelve la respuesta ya convertida.

    Si los reintentos se agotan devuelve None, salvo que sea obligatorio.
    """
    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=1200,
                              headers={"User-Agent": "empresas-sv/1.0"})
            if r.status_code == 200:
                return r.json()
            print("   %s respondio %d" % (servidor, r.status_code))
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))
        espera = 10 * (2 ** intento)
        print("   reintentando %s en %d s..." % (etiqueta, espera))
        time.sleep(espera)
    if obligatorio:
        raise SystemExit("Overpass no respondio (%s). Intenta de nuevo mas tarde." % etiqueta)
    return None


def consulta_de_categoria(categoria, patrones=None):
    filtros = "\n".join("  %s(area.zona);" % f for f in CATEGORIAS[categoria])
    return ("[out:json][timeout:%d][maxsize:%d];\n%s\n.d map_to_area ->.zona;\n(\n%s\n);\n"
            "out tags center;"
            % (TIMEOUT_CONSULTA, MAXSIZE_CONSULTA, seleccion(patrones), filtros))


def descargar_categoria(categoria):
    """Baja una categoria completa; si no pasa, la reintenta distrito por distrito."""
    datos = consultar(consulta_de_categoria(categoria), categoria, obligatorio=False)
    if datos is not None:
        return datos.get("elements", [])

    print("   la consulta completa no paso; probando distrito por distrito...")
    vistos, elementos = set(), []
    for nombre, patron in DISTRITOS:
        parcial = consultar(consulta_de_categoria(categoria, [patron]),
                            "%s / %s" % (categoria, nombre), obligatorio=False)
        if parcial is None:
            print("   sin datos de %s en %s" % (categoria, nombre))
            continue
        for elemento in parcial.get("elements", []):
            clave = (elemento["type"], elemento["id"])
            if clave not in vistos:
                vistos.add(clave)
                elementos.append(elemento)
        time.sleep(3)
    return elementos


# ------------------------------------------------------------ DISTRITOS ---
def descargar_distritos():
    """Baja las fronteras de los distritos (y las guarda en cache)."""
    cache = os.path.join(CARPETA, "_distritos.json")
    if os.path.exists(cache):
        print("Fronteras de distritos: usando la copia guardada.")
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    print("Descargando las fronteras de los %d distritos..." % len(DISTRITOS))
    consulta = ("[out:json][timeout:%d];\n%s\n.d out geom;"
                % (TIMEOUT_CONSULTA, seleccion()))
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
    for llave in LLAVE_PRINCIPAL.get(categoria, []) + LLAVES_TIPO:
        if tags.get(llave):
            subcat = "%s=%s" % (llave, tags[llave])
            break

    calle = valor(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    return {
        "categoria": categoria,
        "subcategoria": subcat,
        "nombre": valor(tags, "name", "name:es", "brand", "operator"),
        "distrito": distrito_de(lat, lon, poligonos),
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
        elementos = descargar_categoria(categoria)
        filas = [f for f in (fila(e, categoria, poligonos) for e in elementos) if f]
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
