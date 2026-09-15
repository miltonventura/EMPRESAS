#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osm_categorias.py
=================

Consulta la base de datos de OpenStreetMap (OSM) para conocer en detalle las
categorías de información que maneja: empresas, comercios, oficinas, centros
comerciales, parques, sitios turísticos, salud, educación, etc.

En OSM las "categorías" se representan con etiquetas (tags) del tipo clave=valor.
Las claves principales que describen lugares/negocios son, por ejemplo:

    amenity=*   servicios (restaurantes, bancos, escuelas, hospitales...)
    shop=*      comercios (supermercados, ropa, ferreterías, centros comerciales...)
    office=*    oficinas y empresas (abogados, seguros, inmobiliarias, TI...)
    craft=*     talleres y oficios (carpinteros, electricistas, sastres...)
    leisure=*   ocio y recreación (parques, gimnasios, piscinas, estadios...)
    tourism=*   turismo (hoteles, museos, atracciones...)
    healthcare=* salud (clínicas, laboratorios, farmacias...)

Fuentes usadas (no requieren clave de API ni registro):

  1. Taginfo  (https://taginfo.openstreetmap.org)  -> catálogo GLOBAL de claves y
     valores usados en toda la base de datos de OSM, con conteos y descripciones.
  2. Overpass API (https://overpass-api.de)        -> conteo LOCAL de cada
     categoría dentro de una ciudad/área concreta (opcional, --area).

Requisitos: Python 3.8+ (solo librería estándar, no hay que instalar nada).

Ejemplos de uso
---------------
    # Catálogo global de las claves principales (top 50 valores por clave)
    python osm_categorias.py

    # Solo comercios y oficinas, 200 valores por clave, exportando a JSON y CSV
    python osm_categorias.py --claves shop office --limite 200 --salida categorias

    # Además, contar cuántos elementos hay de cada categoría en una ciudad
    python osm_categorias.py --claves shop amenity --area "Bogotá"

    # Listar TODAS las claves que existen en OSM (miles), ordenadas por uso
    python osm_categorias.py --todas-las-claves --limite 500
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

# Se pueden cambiar por espejos con variables de entorno, p. ej.:
#   OSM_OVERPASS_URL=https://overpass.kumi.systems/api/interpreter python osm_categorias.py
TAGINFO_URL = os.environ.get("OSM_TAGINFO_URL", "https://taginfo.openstreetmap.org/api/4")
OVERPASS_URL = os.environ.get("OSM_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = "osm-categorias/1.0 (script educativo; python urllib)"

# Claves de OSM que describen "categorías" de lugares, negocios y actividades.
# Descripción corta en español para orientar al lector.
CLAVES_PRINCIPALES = {
    "amenity": "Servicios y equipamientos: restaurantes, bancos, escuelas, hospitales, gasolineras...",
    "shop": "Comercios y tiendas: supermercados, ropa, ferreterías, centros comerciales (shop=mall)...",
    "office": "Oficinas y empresas: abogados, contadores, seguros, inmobiliarias, TI, gobierno...",
    "craft": "Talleres y oficios: carpinterías, electricistas, sastres, panaderías artesanales...",
    "leisure": "Ocio y recreación: parques, gimnasios, piscinas, estadios, parques de diversiones...",
    "tourism": "Turismo: hoteles, museos, atracciones, miradores, campings...",
    "healthcare": "Salud: clínicas, laboratorios, centros de rehabilitación, farmacias...",
    "industrial": "Tipos de instalación industrial: fábricas, refinerías, depósitos...",
    "landuse": "Uso del suelo: comercial, industrial, residencial, retail, agrícola...",
    "building": "Tipo de edificio: comercial, industrial, oficinas, retail, hotel, escuela...",
    "sport": "Deportes practicados en un lugar: fútbol, natación, tenis, gimnasio...",
    "cuisine": "Tipo de cocina de restaurantes/cafés: pizza, sushi, colombiana, vegana...",
    "historic": "Patrimonio histórico: monumentos, castillos, ruinas, memoriales...",
    "man_made": "Estructuras hechas por el hombre: torres, muelles, chimeneas, obras...",
    "natural": "Elementos naturales: bosques, playas, picos, cuerpos de agua...",
    "public_transport": "Transporte público: estaciones, paradas, plataformas...",
    "emergency": "Emergencias: hidrantes, desfibriladores, refugios...",
    "club": "Clubes y asociaciones: deportivos, sociales, culturales...",
    "place": "Tipo de lugar poblado: ciudad, pueblo, barrio, aldea...",
    "brand": "Marca comercial del negocio (cadenas): útil para identificar franquicias.",
}


# --------------------------------------------------------------------------- #
# Utilidades HTTP
# --------------------------------------------------------------------------- #
def _get_json(url, data=None, timeout=120, reintentos=3):
    """Hace una petición HTTP (GET o POST si data != None) y devuelve el JSON."""
    ultimo_error = None
    for intento in range(1, reintentos + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            ultimo_error = exc
            espera = 2 ** intento
            print(f"   [aviso] intento {intento}/{reintentos} falló ({exc}); reintentando en {espera}s...",
                  file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo consultar {url}: {ultimo_error}")


# --------------------------------------------------------------------------- #
# Taginfo: catálogo global de claves y valores
# --------------------------------------------------------------------------- #
def taginfo_estadisticas_clave(clave):
    """Devuelve cuántos objetos (nodos, vías, relaciones) usan una clave a nivel mundial."""
    url = f"{TAGINFO_URL}/key/stats?" + urllib.parse.urlencode({"key": clave})
    datos = _get_json(url)
    return {fila["type"]: fila["count"] for fila in datos.get("data", [])}


def taginfo_valores_clave(clave, limite=50, idioma="es"):
    """
    Lista los valores más usados de una clave (p. ej. shop=supermarket, shop=mall...).

    Devuelve una lista de diccionarios con: valor, conteo, fraccion, en_wiki, descripcion.
    Taginfo pagina de a 'rp' resultados; aquí se piden varias páginas si hace falta.
    """
    resultados = []
    por_pagina = min(limite, 500)
    pagina = 1
    while len(resultados) < limite:
        params = {
            "key": clave,
            "page": pagina,
            "rp": por_pagina,
            "sortname": "count",
            "sortorder": "desc",
            "lang": idioma,
        }
        url = f"{TAGINFO_URL}/key/values?" + urllib.parse.urlencode(params)
        datos = _get_json(url)
        filas = datos.get("data", [])
        if not filas:
            break
        for fila in filas:
            resultados.append({
                "clave": clave,
                "valor": fila["value"],
                "conteo": fila["count"],
                "fraccion": round(fila.get("fraction", 0.0) * 100, 3),
                "en_wiki": bool(fila.get("in_wiki")),
                "descripcion": fila.get("description") or "",
            })
            if len(resultados) >= limite:
                break
        if len(filas) < por_pagina:
            break
        pagina += 1
    return resultados


def taginfo_todas_las_claves(limite=200):
    """Lista TODAS las claves existentes en OSM, ordenadas por cantidad de uso."""
    resultados = []
    por_pagina = min(limite, 500)
    pagina = 1
    while len(resultados) < limite:
        params = {
            "page": pagina,
            "rp": por_pagina,
            "sortname": "count_all",
            "sortorder": "desc",
        }
        url = f"{TAGINFO_URL}/keys/all?" + urllib.parse.urlencode(params)
        datos = _get_json(url)
        filas = datos.get("data", [])
        if not filas:
            break
        for fila in filas:
            resultados.append({
                "clave": fila["key"],
                "conteo": fila["count_all"],
                "valores_distintos": fila.get("values_all", 0),
                "en_wiki": bool(fila.get("in_wiki")),
            })
            if len(resultados) >= limite:
                break
        if len(filas) < por_pagina:
            break
        pagina += 1
    return resultados


# --------------------------------------------------------------------------- #
# Overpass: conteo local dentro de un área (ciudad, departamento, país...)
# --------------------------------------------------------------------------- #
def overpass_conteo_por_valor(clave, area):
    """
    Cuenta, dentro de un área con nombre (p. ej. "Bogotá", "Medellín", "Colombia"),
    cuántos elementos existen por cada valor de la clave dada.

    Usa `out tags;` para traer solo las etiquetas (sin geometría) y agrupa en Python.
    """
    consulta = f"""
    [out:json][timeout:180];
    area["name"="{area}"]["boundary"="administrative"]->.zona;
    nwr(area.zona)["{clave}"];
    out tags;
    """
    datos = _get_json(OVERPASS_URL,
                      data=urllib.parse.urlencode({"data": consulta}).encode("utf-8"),
                      timeout=200)
    contador = Counter()
    for elemento in datos.get("elements", []):
        valor = elemento.get("tags", {}).get(clave)
        if valor:
            # Un objeto puede tener varios valores separados por ';' (p. ej. shop=bakery;coffee)
            for v in valor.split(";"):
                contador[v.strip()] += 1
    return contador


# --------------------------------------------------------------------------- #
# Presentación y exportación
# --------------------------------------------------------------------------- #
def imprimir_tabla(filas, columnas, anchos):
    """Imprime una tabla sencilla en consola."""
    cabecera = " | ".join(c.ljust(a) for c, a in zip(columnas, anchos))
    print(cabecera)
    print("-" * len(cabecera))
    for fila in filas:
        celdas = []
        for c, a in zip(columnas, anchos):
            texto = str(fila.get(c, ""))
            if len(texto) > a:
                texto = texto[: a - 1] + "…"
            celdas.append(texto.ljust(a))
        print(" | ".join(celdas))


def exportar(resultado, base_nombre):
    """Guarda el resultado completo en JSON y una tabla plana en CSV."""
    ruta_json = f"{base_nombre}.json"
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    ruta_csv = f"{base_nombre}.csv"
    with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["clave", "descripcion_clave", "valor", "conteo_global",
                           "porcentaje_global", "en_wiki", "descripcion_valor", "conteo_local"])
        for clave, info in resultado.get("categorias", {}).items():
            for v in info["valores"]:
                escritor.writerow([
                    clave, info["descripcion"], v["valor"], v["conteo"], v["fraccion"],
                    v["en_wiki"], v["descripcion"], v.get("conteo_local", ""),
                ])
    print(f"\nArchivos generados: {ruta_json}  y  {ruta_csv}")


# --------------------------------------------------------------------------- #
# Programa principal
# --------------------------------------------------------------------------- #
def parsear_argumentos():
    p = argparse.ArgumentParser(
        description="Explora las categorías (claves y valores) que maneja OpenStreetMap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Ejemplos de uso")[1] if "Ejemplos de uso" in __doc__ else "",
    )
    p.add_argument("--claves", nargs="+", default=None,
                   help="Claves a consultar (por defecto: todas las claves principales). "
                        f"Disponibles: {', '.join(CLAVES_PRINCIPALES)}")
    p.add_argument("--limite", type=int, default=50,
                   help="Máximo de valores a listar por clave (por defecto 50).")
    p.add_argument("--idioma", default="es",
                   help="Idioma de las descripciones del wiki (es, en, pt, fr...). Por defecto 'es'.")
    p.add_argument("--area", default=None,
                   help='Nombre de un área administrativa (p. ej. "Bogotá", "Colombia") para '
                        "contar cuántos elementos hay localmente de cada categoría (usa Overpass).")
    p.add_argument("--salida", default=None,
                   help="Nombre base de archivo para exportar (genera .json y .csv).")
    p.add_argument("--todas-las-claves", action="store_true",
                   help="En lugar del catálogo por clave, lista TODAS las claves de OSM por uso.")
    p.add_argument("--sin-descripciones", action="store_true",
                   help="No imprimir la columna de descripción (salida más compacta).")
    return p.parse_args()


def main():
    args = parsear_argumentos()

    # Modo 1: listar todas las claves que existen en OSM
    if args.todas_las_claves:
        print(f"Consultando Taginfo: las {args.limite} claves más usadas en OpenStreetMap...\n")
        claves = taginfo_todas_las_claves(args.limite)
        imprimir_tabla(claves, ["clave", "conteo", "valores_distintos", "en_wiki"], [40, 14, 18, 8])
        if args.salida:
            with open(f"{args.salida}.json", "w", encoding="utf-8") as f:
                json.dump(claves, f, ensure_ascii=False, indent=2)
            with open(f"{args.salida}.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["clave", "conteo", "valores_distintos", "en_wiki"])
                w.writeheader()
                w.writerows(claves)
            print(f"\nArchivos generados: {args.salida}.json y {args.salida}.csv")
        return

    # Modo 2: catálogo detallado por clave (categoría)
    claves = args.claves or list(CLAVES_PRINCIPALES)
    resultado = {
        "fuente": "OpenStreetMap vía Taginfo" + (f" + Overpass (área: {args.area})" if args.area else ""),
        "fecha_consulta": time.strftime("%Y-%m-%d %H:%M:%S"),
        "categorias": {},
    }

    for clave in claves:
        descripcion = CLAVES_PRINCIPALES.get(clave, "(clave personalizada)")
        print("=" * 100)
        print(f"CLAVE: {clave}  ->  {descripcion}")
        print("=" * 100)

        try:
            stats = taginfo_estadisticas_clave(clave)
            print(f"Uso global: {stats.get('all', 0):,} objetos "
                  f"(nodos: {stats.get('nodes', 0):,}, vías: {stats.get('ways', 0):,}, "
                  f"relaciones: {stats.get('relations', 0):,})")
            valores = taginfo_valores_clave(clave, args.limite, args.idioma)
        except RuntimeError as exc:
            print(f"   [error] {exc}")
            continue

        conteo_local = None
        if args.area:
            print(f"Consultando Overpass para el área \"{args.area}\" (puede tardar)...")
            try:
                conteo_local = overpass_conteo_por_valor(clave, args.area)
                total_local = sum(conteo_local.values())
                print(f"Elementos con '{clave}' en {args.area}: {total_local:,}")
                for v in valores:
                    v["conteo_local"] = conteo_local.get(v["valor"], 0)
                # Valores que existen localmente pero no están en el top global
                ya_listados = {v["valor"] for v in valores}
                for valor_local, n in conteo_local.most_common():
                    if valor_local not in ya_listados:
                        valores.append({"clave": clave, "valor": valor_local, "conteo": "",
                                        "fraccion": "", "en_wiki": "", "descripcion": "",
                                        "conteo_local": n})
            except RuntimeError as exc:
                print(f"   [error Overpass] {exc}")

        columnas = ["valor", "conteo", "fraccion", "en_wiki"]
        anchos = [32, 12, 9, 8]
        if conteo_local is not None:
            columnas.append("conteo_local")
            anchos.append(13)
        if not args.sin_descripciones:
            columnas.append("descripcion")
            anchos.append(70)
        print()
        imprimir_tabla(valores, columnas, anchos)
        print()

        resultado["categorias"][clave] = {
            "descripcion": descripcion,
            "uso_global": stats,
            "valores": valores,
        }

    if args.salida:
        exportar(resultado, args.salida)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(1)
