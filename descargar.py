#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga registros de OpenStreetMap para los departamentos de San Salvador y
La Libertad (El Salvador), con todos sus municipios y distritos.

Trae TODOS los valores de cada etiqueta de OSM pedida: comercios (shop),
oficinas y empresas (office), talleres (craft), industria (industrial),
servicios (amenity), ocio (leisure), turismo (tourism), clubes (club),
edificios (building), uso del suelo (landuse), lugares poblados (place),
naturales (natural), historicos (historic) e infraestructura (man_made).

La marca (brand), el tipo de cocina (cuisine) y el deporte (sport) no son
grupos aparte: viajan como columnas de cada registro.

Uso:   pip install requests
       python3 descargar.py

Deja un CSV por grupo en la carpeta 'datos', mas un CSV con todo junto y un
GeoJSON. Cada registro queda etiquetado con su departamento, municipio y
distrito.

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import collections
import csv
import json
import os
import time

import requests

# ---------------------------------------------------------------- AJUSTES ---
CARPETA = "datos"   # donde se guardan los resultados

# Departamentos a consultar. El script descubre solo los municipios y distritos
# que hay dentro de ellos; no hay que enumerarlos.
DEPARTAMENTOS = ["San Salvador", "La Libertad"]

# Grupos a descargar: (nombre del archivo, etiqueta de OSM).
# Comenta con # la linea de un grupo que no quieras bajar.
GRUPOS = [
    ("comercios",       "shop"),
    ("oficinas",        "office"),
    ("talleres",        "craft"),
    ("industria",       "industrial"),
    ("servicios",       "amenity"),
    ("ocio",            "leisure"),
    ("turismo",         "tourism"),
    ("clubes",          "club"),
    ("uso_del_suelo",   "landuse"),
    ("lugares",         "place"),
    ("naturales",       "natural"),
    ("historicos",      "historic"),
    ("infraestructura", "man_made"),
    ("edificios",       "building"),
]

# Los edificios son, de lejos, el grupo mas grande: en estos dos departamentos
# puede haber cientos de miles de casas mapeadas. Con False se traen solo los
# edificios con nombre o de uso no residencial, que es lo util para un censo
# de negocios. Ponlo en True si de verdad quieres cada casa.
EDIFICIOS_COMPLETOS = False

# Grupos que se consultan directamente distrito por distrito, sin intentar
# primero la consulta grande, porque se sabe que no cabe de una sola vez.
GRUPOS_PESADOS = {"edificios"}

# Si el total supera este numero de registros, se omite el GeoJSON combinado
# (un archivo de ese tamano no lo abre ningun visor comodamente).
LIMITE_GEOJSON = 200000

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Rectangulo que contiene a El Salvador; acota la busqueda de los limites
# administrativos para que no aparezcan homonimos de otros paises.
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"

# Niveles administrativos por debajo del departamento (municipios y distritos).
NIVELES_INTERNOS = "^(5|6|7|8|9|10)$"

TIMEOUT_CONSULTA = 800   # segundos que se le piden a Overpass
PASO_REJILLA = 0.005     # ~550 m; agrupa los segmentos de frontera por latitud

COLUMNAS = ["grupo", "clave", "valor", "etiqueta_es", "nombre", "marca",
            "operador", "departamento", "municipio", "distrito",
            "latitud", "longitud", "direccion", "ciudad", "telefono", "correo",
            "sitio_web", "horario", "cocina", "deporte", "tipo_club",
            "osm_tipo", "osm_id", "url_osm"]

# Traduccion de los valores de OSM al español. Se completa mas abajo.
ETIQUETAS = {}


# ------------------------------------------------------------- OVERPASS ---
def consultar(consulta, etiqueta, modo="obligatorio"):
    """Envia una consulta a Overpass.

    modo="obligatorio"    -> insiste y aborta el programa si no lo logra.
    modo="puede_partirse" -> si el servidor dice que la consulta es demasiado
                             grande devuelve None enseguida, porque la solucion
                             no es reintentar sino partir el area en pedazos.
    modo="ultimo_recurso" -> ya no hay como partir mas: insiste igual que en
                             obligatorio, pero devuelve None en vez de abortar.
    """
    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        demasiado_grande = False
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=1200,
                              headers={"User-Agent": "empresas-sv/2.0"})
            if r.status_code == 200:
                datos = r.json()
                nota = datos.get("remark", "")
                if "error" in nota.lower():
                    print("   el servidor no pudo con la consulta: %s" % nota.strip())
                    demasiado_grande = True
                else:
                    return datos
            else:
                print("   %s respondio %d" % (servidor, r.status_code))
                demasiado_grande = r.status_code in (400, 504)
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))

        if demasiado_grande and modo == "puede_partirse":
            return None
        if modo == "puede_partirse" and intento >= 1:
            return None
        if intento == 3:
            break
        espera = 10 * (2 ** intento)
        print("   reintentando %s en %d s..." % (etiqueta, espera))
        time.sleep(espera)

    if modo == "obligatorio":
        raise SystemExit("Overpass no respondio (%s). Intenta de nuevo mas tarde." % etiqueta)
    return None


def preambulo(ids=None):
    """Define el area de busqueda: los departamentos, o unas relaciones sueltas."""
    if ids:
        seleccion = "rel(id:%s)" % ",".join(str(i) for i in ids)
    else:
        seleccion = ('rel(%s)["boundary"="administrative"]["admin_level"!="2"]'
                     '["name"~"^(%s)$"]' % (BBOX_PAIS, "|".join(DEPARTAMENTOS)))
    return "%s->.dep;\n.dep map_to_area ->.zona;" % seleccion


def filtros_de(clave):
    """Filtros Overpass de un grupo."""
    if clave == "building" and not EDIFICIOS_COMPLETOS:
        return ['nwr["building"]["name"]',
                'nwr["building"~"^(commercial|retail|industrial|warehouse|office|'
                'hotel|school|university|hospital|church|cathedral|chapel|mosque|'
                'temple|government|civic|public|train_station|stadium|sports_hall|'
                'supermarket|kiosk|construction|farm|barn|greenhouse|hangar)$"]']
    return ['nwr["%s"]' % clave]


def consulta_de_grupo(clave, ids=None):
    cuerpo = "\n".join("  %s(area.zona);" % f for f in filtros_de(clave))
    return ("[out:json][timeout:%d];\n%s\n(\n%s\n);\nout tags center;"
            % (TIMEOUT_CONSULTA, preambulo(ids), cuerpo))


# -------------------------------------------------------------- LIMITES ---
def descargar_limites():
    """Baja los limites de los departamentos y de todo lo que hay dentro."""
    cache = os.path.join(CARPETA, "_limites.json")
    if os.path.exists(cache):
        print("Limites administrativos: usando la copia guardada.")
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    print("Descargando los limites de %s..." % " y ".join(DEPARTAMENTOS))
    consulta = ('[out:json][timeout:%d];\n%s\n(\n  .dep;\n'
                '  rel(area.zona)["boundary"="administrative"]["admin_level"~"%s"];\n'
                ');\nout geom;' % (TIMEOUT_CONSULTA, preambulo(), NIVELES_INTERNOS))
    datos = consultar(consulta, "limites")
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)
    return datos


def nivel_de(tags):
    try:
        return int(tags.get("admin_level", 99))
    except (TypeError, ValueError):
        return 99


def armar_limites(datos):
    """Convierte cada limite en segmentos agrupados por bandas de latitud.

    Descarta los limites de departamentos vecinos que Overpass arrastra por
    tocar la frontera: se quedan solo los que tienen su centro dentro de los
    departamentos pedidos. Devuelve la lista ordenada de lo general a lo
    particular: departamento, luego municipio, luego distrito.
    """
    poligonos, vistos = [], set()
    for relacion in datos.get("elements", []):
        tags = relacion.get("tags", {})
        nombre = tags.get("name", "")
        identificador = relacion.get("id")
        # Se deduplica por id, no por nombre: dos distritos distintos pueden
        # llamarse igual y perder uno dejaria un hueco sin consultar.
        if not nombre or identificador in vistos:
            continue
        vistos.add(identificador)

        rejilla = collections.defaultdict(list)
        suma_lat = suma_lon = puntos_total = 0
        for miembro in relacion.get("members", []):
            if miembro.get("role") == "label":
                continue
            puntos = miembro.get("geometry") or []
            for punto in puntos:
                suma_lat += punto["lat"]
                suma_lon += punto["lon"]
                puntos_total += 1
            for a, b in zip(puntos, puntos[1:]):
                if a["lat"] == b["lat"]:
                    continue   # los segmentos horizontales no cruzan el rayo
                segmento = (a["lat"], a["lon"], b["lat"], b["lon"])
                desde = int(min(a["lat"], b["lat"]) / PASO_REJILLA)
                hasta = int(max(a["lat"], b["lat"]) / PASO_REJILLA)
                for banda in range(desde, hasta + 1):
                    rejilla[banda].append(segmento)
        if not rejilla or not puntos_total:
            continue
        poligonos.append({"nivel": nivel_de(tags), "nombre": nombre,
                          "id": identificador, "rejilla": dict(rejilla),
                          "centro": (suma_lat / puntos_total, suma_lon / puntos_total)})

    departamentos = [p for p in poligonos if p["nivel"] <= 4]
    internos, ajenos = [], 0
    for poligono in poligonos:
        if poligono in departamentos:
            continue
        lat, lon = poligono["centro"]
        if any(contiene(lat, lon, d["rejilla"]) for d in departamentos):
            internos.append(poligono)
        else:
            ajenos += 1
    if ajenos:
        print("  (se descartaron %d limites de departamentos vecinos)" % ajenos)

    limites = departamentos + internos
    limites.sort(key=lambda l: (l["nivel"], l["nombre"]))
    return limites


def contiene(lat, lon, rejilla):
    """Punto en poligono por conteo de cruces, solo con la banda que toca."""
    cruces = 0
    for lat1, lon1, lat2, lon2 in rejilla.get(int(lat / PASO_REJILLA), ()):
        if (lat1 > lat) != (lat2 > lat):
            corte = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < corte:
                cruces += 1
    return cruces % 2 == 1


def ubicacion(lat, lon, limites):
    """Devuelve (departamento, municipio, distrito) del punto."""
    dentro = [(l["nivel"], l["nombre"]) for l in limites
              if contiene(lat, lon, l["rejilla"])]
    if not dentro:
        return "", "", ""
    departamento = next((n for niv, n in dentro if niv <= 4), "")
    internos = [n for niv, n in dentro if niv > 4]
    if not internos:
        return departamento, "", ""
    distrito = internos[-1]
    municipio = internos[-2] if len(internos) >= 2 else distrito
    return departamento, municipio, distrito


def particiones(limites):
    """Formas de partir el area, de la mas gruesa a la mas fina.

    Cada particion es una lista de (nombre, [ids de relacion]) para consultar
    por separado. La primera es el area completa en una sola consulta.
    """
    trozos = [[("todo el territorio", None)]]
    niveles = sorted({l["nivel"] for l in limites if l["nivel"] > 4})
    for nivel in niveles:
        unidades = [(l["nombre"], [l["id"]]) for l in limites
                    if l["nivel"] == nivel and l["id"]]
        if unidades:
            trozos.append(unidades)
    return trozos


# -------------------------------------------------------------- DESCARGA ---
def descargar_grupo(grupo, clave, trozos, limites):
    """Descarga un grupo, partiendo el area si el servidor no puede con ella.

    Devuelve (filas, zonas_fallidas). Cada respuesta se convierte a filas en
    el momento, para no tener en memoria los elementos crudos de un grupo
    entero. En la particion mas fina ya no hay donde replegarse: si una zona
    falla se sigue con las demas y se reporta, en vez de tirar la descarga.
    """
    primera = len(trozos) - 1 if grupo in GRUPOS_PESADOS else 0
    for indice in range(primera, len(trozos)):
        particion = trozos[indice]
        ultima = (indice == len(trozos) - 1)
        if len(particion) > 1:
            print("  consultando %d zonas por separado..." % len(particion))

        filas, fallidas, replegarse = {}, [], False
        for numero, (nombre, ids) in enumerate(particion, 1):
            datos = consultar(consulta_de_grupo(clave, ids),
                              "%s / %s" % (grupo, nombre),
                              "ultimo_recurso" if ultima else "puede_partirse")
            if datos is None:
                if not ultima:
                    print("  no se pudo con '%s'; probando una division mas fina"
                          % nombre)
                    replegarse = True
                    break
                print("  AVISO: '%s' no se pudo descargar; queda incompleto" % nombre)
                fallidas.append(nombre)
                continue
            for elemento in datos.get("elements", []):
                registro = fila(elemento, grupo, clave, limites)
                if registro:
                    filas[(registro["osm_tipo"], registro["osm_id"])] = registro
            if len(particion) > 1:
                print("    %3d/%d %-28s %7d acumulados"
                      % (numero, len(particion), nombre[:28], len(filas)))
                time.sleep(2)
        if not replegarse:
            return list(filas.values()), fallidas
    return [], ["todo el grupo"]


# -------------------------------------------------------------- SALIDA ---
def valor(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def fila(elemento, grupo, clave, limites):
    tags = elemento.get("tags", {})
    centro = elemento.get("center", {})
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None

    crudo = tags.get(clave, "")
    calle = valor(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    departamento, municipio, distrito = ubicacion(lat, lon, limites)
    return {
        "grupo": grupo,
        "clave": clave,
        "valor": crudo,
        "etiqueta_es": ETIQUETAS.get(clave, {}).get(crudo, ""),
        "nombre": valor(tags, "name", "name:es", "brand", "operator"),
        "marca": valor(tags, "brand", "brand:wikidata"),
        "operador": tags.get("operator", ""),
        "departamento": departamento,
        "municipio": municipio,
        "distrito": distrito,
        "latitud": lat,
        "longitud": lon,
        "direccion": ("%s %s" % (calle, numero)).strip(),
        "ciudad": valor(tags, "addr:city", "addr:municipality"),
        "telefono": valor(tags, "phone", "contact:phone", "contact:mobile"),
        "correo": valor(tags, "email", "contact:email"),
        "sitio_web": valor(tags, "website", "contact:website", "contact:facebook"),
        "horario": tags.get("opening_hours", ""),
        "cocina": tags.get("cuisine", ""),
        "deporte": tags.get("sport", ""),
        "tipo_club": tags.get("club", ""),
        "osm_tipo": elemento["type"],
        "osm_id": elemento["id"],
        "url_osm": "https://www.openstreetmap.org/%s/%s" % (elemento["type"], elemento["id"]),
    }


def guardar_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def main():
    os.makedirs(CARPETA, exist_ok=True)

    limites = armar_limites(descargar_limites())
    por_nivel = collections.defaultdict(list)
    for l in limites:
        por_nivel[l["nivel"]].append(l["nombre"])
    for nivel in sorted(por_nivel):
        nombres = sorted(por_nivel[nivel])
        muestra = ", ".join(nombres[:5]) + (", ..." if len(nombres) > 5 else "")
        print("  nivel %-2d  %3d limites   %s" % (nivel, len(nombres), muestra))

    encontrados = [l["nombre"] for l in limites if l["nivel"] <= 4]
    for esperado in DEPARTAMENTOS:
        if esperado not in encontrados:
            print("  OJO: no se encontro el limite del departamento de %s. "
                  "La busqueda puede quedar incompleta." % esperado)
    if not [l for l in limites if l["nivel"] > 4]:
        print("  OJO: no se encontro ningun municipio ni distrito; las columnas "
              "municipio y distrito iran vacias.")
    trozos = particiones(limites)
    print()

    todas, incompletos = {}, {}
    for grupo, clave in GRUPOS:
        print("Descargando %s (%s=*)..." % (grupo, clave))
        filas, fallidas = descargar_grupo(grupo, clave, trozos, limites)
        if fallidas:
            incompletos[grupo] = fallidas
        filas.sort(key=lambda f: (f["municipio"], f["distrito"], f["valor"],
                                  f["nombre"] == "", f["nombre"].lower()))

        ruta = os.path.join(CARPETA, "osm_%s.csv" % grupo)
        guardar_csv(ruta, filas)
        print("  %d registros (%d con nombre)  ->  %s"
              % (len(filas), sum(1 for f in filas if f["nombre"]), ruta))

        for f in filas:
            llave = (f["osm_tipo"], f["osm_id"])
            if llave in todas:
                todas[llave]["grupo"] += "|" + f["grupo"]
                todas[llave]["clave"] += "|" + f["clave"]
                todas[llave]["valor"] += "|" + f["valor"]
                if f["etiqueta_es"]:
                    previa = todas[llave]["etiqueta_es"]
                    todas[llave]["etiqueta_es"] = (previa + "|" if previa else "") + f["etiqueta_es"]
            else:
                todas[llave] = dict(f)
        time.sleep(3)   # pausa amable con el servidor publico

    filas = sorted(todas.values(),
                   key=lambda f: (f["municipio"], f["distrito"], f["grupo"],
                                  f["nombre"].lower()))
    guardar_csv(os.path.join(CARPETA, "osm_todo.csv"), filas)

    print("\nTotal sin duplicados: %d registros" % len(filas))
    por_distrito = collections.Counter(f["distrito"] or "(sin distrito)" for f in filas)
    for nombre, cuantos in sorted(por_distrito.items()):
        print("  %-28s %6d" % (nombre, cuantos))

    if incompletos:
        print("\nZonas que el servidor no pudo entregar (datos incompletos ahi):")
        for grupo, zonas in sorted(incompletos.items()):
            print("  %-18s %s" % (grupo, ", ".join(zonas)))
        print("  Vuelve a correr el script mas tarde para completarlas.")

    print("\n  %s/osm_todo.csv" % CARPETA)
    if len(filas) <= LIMITE_GEOJSON:
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [f["longitud"], f["latitud"]]},
             "properties": f}
            for f in filas]}
        with open(os.path.join(CARPETA, "osm_todo.geojson"), "w", encoding="utf-8") as fh:
            json.dump(geojson, fh, ensure_ascii=False)
        print("  %s/osm_todo.geojson" % CARPETA)
    else:
        print("  (GeoJSON omitido: %d registros superan el limite de %d; "
              "usa los CSV)" % (len(filas), LIMITE_GEOJSON))
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL.")


if __name__ == "__main__":
    main()
