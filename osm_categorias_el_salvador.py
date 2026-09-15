#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osm_categorias_el_salvador.py
=============================

Genera un archivo CSV con TODAS las categorías de información que OpenStreetMap
(OSM) maneja para EL SALVADOR: empresas, comercios, centros comerciales, parques
recreativos, oficinas, turismo, salud, educación, industria, etc.

Cómo funciona
-------------
En OSM cada lugar se clasifica con etiquetas clave=valor (p. ej. shop=mall es un
centro comercial, leisure=park es un parque, office=company es una empresa).

  1. Con la Overpass API se descargan todos los elementos de El Salvador que tienen
     alguna de las claves de categoría (amenity, shop, office, leisure, ...).
  2. Se cuenta cuántos elementos hay en el país de cada clave=valor, cuántos tienen
     nombre y se guardan algunos nombres de ejemplo.
  3. Con Taginfo se agrega la descripción oficial (en español, y en inglés si no
     hay traducción), el uso global y el enlace al wiki de OSM.
  4. Se escriben dos CSV:
        categorias_el_salvador.csv          -> detalle de cada categoría (clave=valor)
        categorias_el_salvador_resumen.csv  -> totales por clave (grupo de categorías)

Requisitos: Python 3.8+ (solo librería estándar, no hay que instalar nada).

Uso
---
    python osm_categorias_el_salvador.py
    python osm_categorias_el_salvador.py --salida mis_categorias.csv
    python osm_categorias_el_salvador.py --claves shop office amenity leisure
    python osm_categorias_el_salvador.py --sin-edificios     # omite building=* (más rápido)
    python osm_categorias_el_salvador.py --pais HN           # otro país por código ISO
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
from collections import Counter, defaultdict

TAGINFO_URL = os.environ.get("OSM_TAGINFO_URL", "https://taginfo.openstreetmap.org/api/4")
OVERPASS_URL = os.environ.get("OSM_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = "osm-categorias-el-salvador/1.0 (script educativo; python urllib)"

PAIS_ISO_DEFECTO = "SV"          # El Salvador
NOMBRES_PAIS = {"SV": "El Salvador"}

# Claves de OSM que representan "categorías" de lugares, negocios y actividades.
# Nombre del grupo en español + descripción.
GRUPOS = {
    "amenity":          ("Servicios y equipamientos",
                         "Restaurantes, bancos, escuelas, hospitales, gasolineras, iglesias, parqueos..."),
    "shop":             ("Comercios y tiendas",
                         "Supermercados, ropa, ferreterías, farmacias, centros comerciales (shop=mall)..."),
    "office":           ("Oficinas y empresas",
                         "Empresas (office=company), abogados, contadores, seguros, inmobiliarias, TI, gobierno..."),
    "craft":            ("Talleres y oficios",
                         "Carpinterías, electricistas, sastres, mecánicos, panaderías artesanales..."),
    "leisure":          ("Ocio y recreación",
                         "Parques (leisure=park), gimnasios, piscinas, estadios, canchas, parques de diversiones..."),
    "tourism":          ("Turismo y hospedaje",
                         "Hoteles, hostales, museos, atracciones, miradores, campings..."),
    "healthcare":       ("Salud",
                         "Clínicas, laboratorios, centros de rehabilitación, consultorios..."),
    "industrial":       ("Industria",
                         "Tipos de instalación industrial: fábricas, bodegas, refinerías..."),
    "landuse":          ("Uso del suelo",
                         "Zonas comerciales, industriales, residenciales, comerciales minoristas, agrícolas..."),
    "building":         ("Tipo de edificio",
                         "Comercial, industrial, oficinas, retail, hotel, escuela, iglesia, vivienda..."),
    "sport":            ("Deportes",
                         "Deporte que se practica en un lugar: fútbol, natación, tenis, gimnasio..."),
    "cuisine":          ("Tipo de cocina",
                         "Cocina de restaurantes y cafés: pupusas, pizza, mariscos, china, cafetería..."),
    "historic":         ("Patrimonio histórico",
                         "Monumentos, ruinas, memoriales, sitios arqueológicos..."),
    "man_made":         ("Infraestructura y estructuras",
                         "Torres, muelles, chimeneas, plantas de tratamiento, obras..."),
    "natural":          ("Elementos naturales",
                         "Playas, volcanes, bosques, lagos, cuerpos de agua..."),
    "public_transport": ("Transporte público",
                         "Estaciones, paradas de bus, plataformas, terminales..."),
    "aeroway":          ("Aeropuertos y aviación",
                         "Aeropuertos, aeródromos, helipuertos, terminales..."),
    "emergency":        ("Emergencias",
                         "Hidrantes, desfibriladores, refugios, estaciones de socorro..."),
    "club":             ("Clubes y asociaciones",
                         "Clubes deportivos, sociales, culturales..."),
    "place":            ("Lugares poblados",
                         "Ciudades, pueblos, cantones, caseríos, colonias, barrios..."),
    "brand":            ("Marcas y cadenas",
                         "Marca comercial del negocio: útil para identificar franquicias y cadenas."),
}
CLAVES_PESADAS = {"building"}   # muchos elementos: se pueden omitir con --sin-edificios


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _get_json(url, data=None, timeout=300, reintentos=3):
    ultimo_error = None
    for intento in range(1, reintentos + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            ultimo_error = exc
            espera = 5 * intento
            print(f"   [aviso] intento {intento}/{reintentos} falló ({exc}); reintento en {espera}s...",
                  file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo consultar {url}: {ultimo_error}")


# --------------------------------------------------------------------------- #
# Overpass: elementos del país por clave
# --------------------------------------------------------------------------- #
def overpass_elementos_pais(clave, pais_iso):
    """
    Descarga (solo etiquetas, sin geometría) todos los nodos, vías y relaciones
    del país que tienen la clave indicada.
    """
    consulta = f"""
    [out:json][timeout:300][maxsize:1073741824];
    area["ISO3166-1"="{pais_iso}"]["admin_level"="2"]->.pais;
    nwr(area.pais)["{clave}"];
    out tags;
    """
    datos = _get_json(OVERPASS_URL,
                      data=urllib.parse.urlencode({"data": consulta}).encode("utf-8"),
                      timeout=360)
    return datos.get("elements", [])


def resumir_por_valor(clave, elementos, max_ejemplos=5):
    """
    Agrupa los elementos por valor de la clave. Devuelve dict valor -> estadísticas.
    """
    stats = defaultdict(lambda: {"total": 0, "nodos": 0, "vias": 0, "relaciones": 0,
                                 "con_nombre": 0, "ejemplos": []})
    tipo_a_campo = {"node": "nodos", "way": "vias", "relation": "relaciones"}
    for el in elementos:
        tags = el.get("tags", {})
        valor_crudo = tags.get(clave)
        if not valor_crudo:
            continue
        nombre = tags.get("name") or tags.get("name:es") or tags.get("brand") or ""
        # Un elemento puede tener varios valores separados por ';' (p. ej. cuisine=pizza;burger)
        for valor in {v.strip() for v in valor_crudo.split(";") if v.strip()}:
            s = stats[valor]
            s["total"] += 1
            s[tipo_a_campo.get(el.get("type"), "nodos")] += 1
            if nombre:
                s["con_nombre"] += 1
                if len(s["ejemplos"]) < max_ejemplos and nombre not in s["ejemplos"]:
                    s["ejemplos"].append(nombre)
    return stats


# --------------------------------------------------------------------------- #
# Taginfo: descripciones y uso global
# --------------------------------------------------------------------------- #
def taginfo_descripciones(clave, valores_necesarios, idioma, max_paginas=10):
    """
    Devuelve dict valor -> {"descripcion", "uso_global", "en_wiki"} consultando las
    páginas de valores de Taginfo hasta cubrir los valores necesarios.
    """
    info = {}
    pendientes = set(valores_necesarios)
    por_pagina = 500
    for pagina in range(1, max_paginas + 1):
        if not pendientes:
            break
        params = {"key": clave, "page": pagina, "rp": por_pagina,
                  "sortname": "count", "sortorder": "desc", "lang": idioma}
        try:
            datos = _get_json(f"{TAGINFO_URL}/key/values?" + urllib.parse.urlencode(params))
        except RuntimeError as exc:
            print(f"   [aviso Taginfo] {exc}", file=sys.stderr)
            break
        filas = datos.get("data", [])
        for fila in filas:
            v = fila["value"]
            info[v] = {"descripcion": (fila.get("description") or "").strip(),
                       "uso_global": fila.get("count", 0),
                       "en_wiki": bool(fila.get("in_wiki"))}
            pendientes.discard(v)
        if len(filas) < por_pagina:
            break
    return info


def taginfo_descripcion_tag(clave, valor, idiomas=("es", "en")):
    """Descripción de un tag concreto desde sus páginas de wiki (respaldo, una petición)."""
    params = {"key": clave, "value": valor}
    try:
        datos = _get_json(f"{TAGINFO_URL}/tag/wiki_pages?" + urllib.parse.urlencode(params))
    except RuntimeError:
        return ""
    por_idioma = {p.get("lang"): (p.get("description") or "").strip() for p in datos.get("data", [])}
    for idioma in idiomas:
        if por_idioma.get(idioma):
            return por_idioma[idioma]
    return ""


def enlace_wiki(clave, valor):
    return "https://wiki.openstreetmap.org/wiki/Tag:" + urllib.parse.quote(f"{clave}={valor}")


# --------------------------------------------------------------------------- #
# Programa principal
# --------------------------------------------------------------------------- #
def parsear_argumentos():
    p = argparse.ArgumentParser(
        description="Genera un CSV con todas las categorías de OpenStreetMap presentes en El Salvador.")
    p.add_argument("--pais", default=PAIS_ISO_DEFECTO,
                   help="Código ISO 3166-1 del país (por defecto SV = El Salvador).")
    p.add_argument("--claves", nargs="+", default=None,
                   help="Claves a analizar (por defecto todas). Disponibles: " + ", ".join(GRUPOS))
    p.add_argument("--sin-edificios", action="store_true",
                   help="Omitir building=* (es la clave con más elementos y la más lenta).")
    p.add_argument("--salida", default="categorias_el_salvador.csv",
                   help="Nombre del CSV de detalle (por defecto categorias_el_salvador.csv).")
    p.add_argument("--idioma", default="es",
                   help="Idioma preferido de las descripciones (por defecto es; respaldo en).")
    p.add_argument("--max-respaldo-wiki", type=int, default=150,
                   help="Máximo de consultas individuales al wiki para valores sin descripción.")
    p.add_argument("--pausa", type=float, default=2.0,
                   help="Segundos de pausa entre consultas a Overpass (cortesía con el servidor).")
    return p.parse_args()


def main():
    args = parsear_argumentos()
    pais = args.pais.upper()
    nombre_pais = NOMBRES_PAIS.get(pais, pais)
    claves = args.claves or list(GRUPOS)
    if args.sin_edificios:
        claves = [c for c in claves if c not in CLAVES_PESADAS]

    base, _ = os.path.splitext(args.salida)
    salida_detalle = args.salida
    salida_resumen = f"{base}_resumen.csv"
    salida_json = f"{base}.json"

    print(f"País: {nombre_pais} ({pais})")
    print(f"Claves a analizar: {', '.join(claves)}\n")

    filas_detalle = []
    filas_resumen = []
    consultas_wiki_restantes = args.max_respaldo_wiki
    inicio = time.time()

    for i, clave in enumerate(claves, 1):
        grupo, desc_grupo = GRUPOS.get(clave, (clave, "(clave personalizada)"))
        print(f"[{i}/{len(claves)}] {clave}  ({grupo})")

        # 1) Overpass: elementos del país
        try:
            elementos = overpass_elementos_pais(clave, pais)
        except RuntimeError as exc:
            print(f"   [error Overpass] {exc}  -> se omite esta clave")
            filas_resumen.append({"clave": clave, "grupo": grupo, "descripcion_grupo": desc_grupo,
                                  "total_elementos": "ERROR", "valores_distintos": "",
                                  "elementos_con_nombre": ""})
            continue
        stats = resumir_por_valor(clave, elementos)
        total = sum(s["total"] for s in stats.values())
        con_nombre = sum(s["con_nombre"] for s in stats.values())
        print(f"   Overpass: {len(elementos):,} elementos, {len(stats)} valores distintos")

        # 2) Taginfo: descripciones (idioma preferido y respaldo en inglés)
        info_es = taginfo_descripciones(clave, stats.keys(), args.idioma)
        info_en = taginfo_descripciones(clave, stats.keys(), "en") if args.idioma != "en" else {}

        for valor, s in sorted(stats.items(), key=lambda kv: -kv[1]["total"]):
            i_es = info_es.get(valor, {})
            i_en = info_en.get(valor, {})
            descripcion = i_es.get("descripcion") or i_en.get("descripcion") or ""
            if not descripcion and consultas_wiki_restantes > 0 and (i_es.get("en_wiki") or i_en.get("en_wiki")):
                descripcion = taginfo_descripcion_tag(clave, valor, (args.idioma, "en"))
                consultas_wiki_restantes -= 1
            filas_detalle.append({
                "grupo": grupo,
                "descripcion_grupo": desc_grupo,
                "clave": clave,
                "valor": valor,
                "etiqueta": f"{clave}={valor}",
                "cantidad_en_pais": s["total"],
                "nodos": s["nodos"],
                "vias": s["vias"],
                "relaciones": s["relaciones"],
                "con_nombre": s["con_nombre"],
                "ejemplos_nombres": " | ".join(s["ejemplos"]),
                "descripcion": descripcion,
                "uso_global_osm": i_es.get("uso_global") or i_en.get("uso_global") or "",
                "documentado_en_wiki": "sí" if (i_es.get("en_wiki") or i_en.get("en_wiki")) else "no",
                "enlace_wiki": enlace_wiki(clave, valor),
            })

        filas_resumen.append({"clave": clave, "grupo": grupo, "descripcion_grupo": desc_grupo,
                              "total_elementos": total, "valores_distintos": len(stats),
                              "elementos_con_nombre": con_nombre})
        time.sleep(args.pausa)

    # 3) Escritura de archivos
    columnas = ["grupo", "descripcion_grupo", "clave", "valor", "etiqueta", "cantidad_en_pais",
                "nodos", "vias", "relaciones", "con_nombre", "ejemplos_nombres", "descripcion",
                "uso_global_osm", "documentado_en_wiki", "enlace_wiki"]
    # utf-8-sig para que Excel reconozca acentos y ñ
    with open(salida_detalle, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas_detalle)
    with open(salida_resumen, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["clave", "grupo", "descripcion_grupo", "total_elementos",
                                          "valores_distintos", "elementos_con_nombre"])
        w.writeheader()
        w.writerows(filas_resumen)
    with open(salida_json, "w", encoding="utf-8") as f:
        json.dump({"pais": nombre_pais, "iso": pais, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "resumen": filas_resumen, "detalle": filas_detalle}, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"Resumen para {nombre_pais}:")
    for r in filas_resumen:
        print(f"  {r['clave']:<18} {r['grupo']:<32} elementos: {str(r['total_elementos']):>8}  "
              f"categorías: {str(r['valores_distintos']):>5}")
    print("=" * 80)
    print(f"Categorías (clave=valor) encontradas: {len(filas_detalle)}")
    print(f"Archivos generados:\n  {salida_detalle}\n  {salida_resumen}\n  {salida_json}")
    print(f"Tiempo total: {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(1)
