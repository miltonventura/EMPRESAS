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
  4. Se escriben los resultados (se guardan progresivamente, clave por clave):
        categorias_el_salvador.csv          -> detalle de cada categoría (clave=valor)
        categorias_el_salvador_resumen.csv  -> totales por clave (grupo de categorías)
        lugares_el_salvador.csv             -> producto directo de la consulta: cada lugar
                                               con nombre, dirección, contacto y coordenadas
        categorias_el_salvador.json         -> categorías y resumen en JSON
        osm_crudo/SV_<clave>.json           -> (con --guardar-crudo) respuesta original de Overpass

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
import http.client
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

TAGINFO_URL = os.environ.get("OSM_TAGINFO_URL", "https://taginfo.openstreetmap.org/api/4")
# Espejos públicos de Overpass. Si uno responde 504/429 (saturado) se prueba el siguiente.
# Con la variable de entorno OSM_OVERPASS_URL se fuerza un único servidor.
OVERPASS_ESPEJOS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
if os.environ.get("OSM_OVERPASS_URL"):
    OVERPASS_ESPEJOS = [os.environ["OSM_OVERPASS_URL"]]
USER_AGENT = "osm-categorias-el-salvador/1.0 (script educativo; python urllib)"

PAIS_ISO_DEFECTO = "SV"          # El Salvador
NOMBRES_PAIS = {"SV": "El Salvador"}
# Rectángulo (sur, oeste, norte, este) que envuelve al país. Acota la consulta y la hace
# mucho más rápida; el filtro por área se aplica después para excluir países vecinos.
BBOX_PAIS = {"SV": "13.10,-90.20,14.50,-87.65"}

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
_CONTEXTO_SSL = None   # se rellena con un contexto sin verificación solo si el usuario lo pide


def _get_json(url, data=None, timeout=300, reintentos=3):
    """Petición HTTP (GET, o POST si data != None) que devuelve el JSON de respuesta."""
    ultimo_error = None
    for intento in range(1, reintentos + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=_CONTEXTO_SSL) as resp:
                cuerpo = resp.read().decode("utf-8", errors="replace")
            return json.loads(cuerpo)
        except urllib.error.HTTPError as exc:
            detalle = ""
            try:
                detalle = exc.read().decode("utf-8", errors="replace")[:300].strip()
            except Exception:
                pass
            ultimo_error = f"HTTP {exc.code} {exc.reason}. {detalle}"
            if exc.code == 429:
                ultimo_error += " (demasiadas peticiones: el servidor pide esperar)"
                espera = 30 * intento
            elif exc.code in (502, 503, 504):
                ultimo_error += " (servidor saturado o consulta demasiado lenta)"
                espera = 15 * intento
            elif exc.code == 400:
                ultimo_error += " (consulta rechazada; revisa la sintaxis o el tamaño)"
                espera = 5
            else:
                espera = 5 * intento
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            ultimo_error = str(exc)
            if "CERTIFICATE_VERIFY_FAILED" in ultimo_error:
                ultimo_error += ("\n   -> Tu Python no encuentra los certificados raíz. En macOS ejecuta "
                                 "'Install Certificates.command' de la carpeta de Python, o vuelve a correr "
                                 "el script con --sin-verificar-ssl.")
                raise RuntimeError(f"No se pudo consultar {url}: {ultimo_error}")
            espera = 5 * intento
        print(f"   [aviso] intento {intento}/{reintentos} falló: {ultimo_error}", file=sys.stderr)
        if intento < reintentos:
            print(f"   [aviso] reintentando en {espera}s...", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo consultar {url}: {ultimo_error}")


# --------------------------------------------------------------------------- #
# Overpass: elementos del país por clave
# --------------------------------------------------------------------------- #
def overpass_elementos_pais(clave, pais_iso, rondas=4):
    """
    Descarga (solo etiquetas, sin geometría) todos los nodos, vías y relaciones
    del país que tienen la clave indicada.

    Prueba cada espejo de Overpass; si todos fallan (normalmente por saturación,
    HTTP 504/429) espera y vuelve a intentar hasta 'rondas' veces.
    """
    bbox = BBOX_PAIS.get(pais_iso)
    filtro_bbox = f"({bbox})" if bbox else ""
    consulta = f"""
    [out:json][timeout:180];
    area["ISO3166-1"="{pais_iso}"]["admin_level"="2"]->.pais;
    nwr["{clave}"]{filtro_bbox}(area.pais);
    out tags center;
    """
    cuerpo = urllib.parse.urlencode({"data": consulta}).encode("utf-8")
    ultimo_error = None
    for ronda in range(1, rondas + 1):
        for url in OVERPASS_ESPEJOS:
            try:
                datos = _get_json(url, data=cuerpo, timeout=240, reintentos=1)
                if "elements" not in datos:
                    raise RuntimeError(f"respuesta inesperada de {url}: {str(datos)[:200]}")
                if url != OVERPASS_ESPEJOS[0]:
                    print(f"   (respondió el espejo {url.split('/')[2]})")
                return datos["elements"]
            except RuntimeError as exc:
                ultimo_error = exc
                print(f"   [aviso] {url.split('/')[2]} no respondió; probando otro espejo...",
                      file=sys.stderr)
        if ronda < rondas:
            espera = 45 * ronda
            print(f"   [aviso] todos los servidores están saturados; esperando {espera}s "
                  f"(ronda {ronda}/{rondas})...", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Overpass no respondió tras {rondas} rondas. Último error: {ultimo_error}")


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


COLUMNAS_LUGARES = ["grupo", "clave", "valor", "etiqueta", "nombre", "marca", "tipo_osm", "id_osm",
                    "direccion", "ciudad", "departamento", "telefono", "sitio_web", "correo",
                    "horario", "latitud", "longitud", "enlace_osm", "otras_etiquetas"]


def filas_lugares(clave, grupo, elementos):
    """
    Convierte los elementos devueltos por Overpass en filas de lugares: una por
    elemento (nombre, dirección, contacto, coordenadas). Es el producto directo
    de la consulta a OSM.
    """
    filas = []
    for el in elementos:
        tags = el.get("tags", {})
        valor = tags.get(clave, "")
        if not valor:
            continue
        centro = el.get("center") or {}
        lat = el.get("lat", centro.get("lat", ""))
        lon = el.get("lon", centro.get("lon", ""))
        direccion = " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x)
        if tags.get("addr:full"):
            direccion = tags["addr:full"]
        usadas = {clave, "name", "name:es", "brand", "addr:street", "addr:housenumber", "addr:full",
                  "addr:city", "addr:state", "phone", "contact:phone", "website", "contact:website",
                  "email", "contact:email", "opening_hours"}
        otras = "; ".join(f"{k}={v}" for k, v in sorted(tags.items()) if k not in usadas)
        filas.append({
            "grupo": grupo,
            "clave": clave,
            "valor": valor,
            "etiqueta": f"{clave}={valor}",
            "nombre": tags.get("name") or tags.get("name:es") or "",
            "marca": tags.get("brand", ""),
            "tipo_osm": el.get("type", ""),
            "id_osm": el.get("id", ""),
            "direccion": direccion,
            "ciudad": tags.get("addr:city", ""),
            "departamento": tags.get("addr:state", ""),
            "telefono": tags.get("phone") or tags.get("contact:phone") or "",
            "sitio_web": tags.get("website") or tags.get("contact:website") or "",
            "correo": tags.get("email") or tags.get("contact:email") or "",
            "horario": tags.get("opening_hours", ""),
            "latitud": lat,
            "longitud": lon,
            "enlace_osm": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
            "otras_etiquetas": otras,
        })
    return filas


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
    p.add_argument("--guardar-crudo", action="store_true",
                   help="Guardar además la respuesta JSON original de Overpass de cada clave "
                        "en la carpeta osm_crudo/.")
    p.add_argument("--sin-lugares", action="store_true",
                   help="No generar el CSV de lugares (solo el de categorías).")
    p.add_argument("--sin-verificar-ssl", action="store_true",
                   help="Desactiva la verificación de certificados (solo si falla con CERTIFICATE_VERIFY_FAILED).")
    p.add_argument("--pausa", type=float, default=2.0,
                   help="Segundos de pausa entre consultas a Overpass (cortesía con el servidor).")
    return p.parse_args()


def main():
    global _CONTEXTO_SSL
    args = parsear_argumentos()
    if args.sin_verificar_ssl:
        _CONTEXTO_SSL = ssl._create_unverified_context()
        print("[aviso] Verificación SSL desactivada por petición del usuario.", file=sys.stderr)
    pais = args.pais.upper()
    nombre_pais = NOMBRES_PAIS.get(pais, pais)
    claves = args.claves or list(GRUPOS)
    if args.sin_edificios:
        claves = [c for c in claves if c not in CLAVES_PESADAS]

    base, _ = os.path.splitext(args.salida)
    salida_detalle = os.path.abspath(args.salida)
    salida_resumen = os.path.abspath(f"{base}_resumen.csv")
    salida_json = os.path.abspath(f"{base}.json")
    salida_lugares = os.path.abspath(f"{base.replace('categorias', 'lugares') if 'categorias' in base else base + '_lugares'}.csv")
    carpeta_crudo = os.path.abspath("osm_crudo")
    if args.guardar_crudo:
        os.makedirs(carpeta_crudo, exist_ok=True)

    print(f"País: {nombre_pais} ({pais})")
    print(f"Servidores Overpass: {', '.join(u.split('/')[2] for u in OVERPASS_ESPEJOS)}")
    print(f"Claves a analizar: {', '.join(claves)}\n")

    filas_detalle = []
    filas_resumen = []
    total_lugares = 0
    consultas_wiki_restantes = args.max_respaldo_wiki
    inicio = time.time()

    columnas = ["grupo", "descripcion_grupo", "clave", "valor", "etiqueta", "cantidad_en_pais",
                "nodos", "vias", "relaciones", "con_nombre", "ejemplos_nombres", "descripcion",
                "uso_global_osm", "documentado_en_wiki", "enlace_wiki"]
    columnas_resumen = ["clave", "grupo", "descripcion_grupo", "total_elementos",
                        "valores_distintos", "elementos_con_nombre"]

    def escribir_archivos():
        """Escribe (o reescribe) los CSV y el JSON con lo acumulado hasta ahora."""
        # utf-8-sig para que Excel reconozca acentos y ñ
        with open(salida_detalle, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columnas)
            w.writeheader()
            w.writerows(filas_detalle)
        with open(salida_resumen, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columnas_resumen)
            w.writeheader()
            w.writerows(filas_resumen)
        with open(salida_json, "w", encoding="utf-8") as f:
            json.dump({"pais": nombre_pais, "iso": pais, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "resumen": filas_resumen, "detalle": filas_detalle}, f, ensure_ascii=False, indent=2)

    if not args.sin_lugares:
        # El CSV de lugares se va llenando clave por clave (puede ser grande)
        with open(salida_lugares, "w", encoding="utf-8-sig", newline="") as f:
            csv.DictWriter(f, fieldnames=COLUMNAS_LUGARES).writeheader()

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

        if args.guardar_crudo:
            ruta_cruda = os.path.join(carpeta_crudo, f"{pais}_{clave}.json")
            with open(ruta_cruda, "w", encoding="utf-8") as f:
                json.dump(elementos, f, ensure_ascii=False)
            print(f"   Respuesta original guardada en {ruta_cruda}")

        if not args.sin_lugares:
            lugares = filas_lugares(clave, grupo, elementos)
            with open(salida_lugares, "a", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=COLUMNAS_LUGARES).writerows(lugares)
            total_lugares += len(lugares)
            print(f"   {len(lugares):,} lugares agregados a {os.path.basename(salida_lugares)}")

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
        escribir_archivos()   # guardado progresivo: si algo falla después, esto ya está en disco
        time.sleep(args.pausa)

    escribir_archivos()

    print("\n" + "=" * 80)
    print(f"Resumen para {nombre_pais}:")
    for r in filas_resumen:
        print(f"  {r['clave']:<18} {r['grupo']:<32} elementos: {str(r['total_elementos']):>8}  "
              f"categorías: {str(r['valores_distintos']):>5}")
    print("=" * 80)
    print(f"Categorías (clave=valor) encontradas: {len(filas_detalle)}")
    if not args.sin_lugares:
        print(f"Lugares descargados: {total_lugares:,}")
    print("Archivos generados:")
    print(f"  {salida_detalle}   <- categorías encontradas en el país, con descripción")
    print(f"  {salida_resumen}   <- totales por grupo")
    if not args.sin_lugares:
        print(f"  {salida_lugares}   <- todos los lugares (nombre, dirección, contacto, coordenadas)")
    print(f"  {salida_json}   <- lo mismo que los dos primeros CSV, en JSON")
    if args.guardar_crudo:
        print(f"  {carpeta_crudo}{os.sep}   <- respuestas originales de Overpass")
    print(f"Tiempo total: {time.time() - inicio:.0f} s")
    if not filas_detalle:
        print("\nATENCIÓN: no se obtuvo ningún dato. Todas las consultas a Overpass fallaron; "
              "los CSV quedaron vacíos. Revisa los mensajes [error Overpass] de arriba y "
              "vuelve a intentarlo más tarde.")


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        sys.exit("Este script necesita Python 3.8 o superior. Versión actual: " + sys.version.split()[0])
    # Evita errores de codificación en consolas de Windows con acentos y eñes
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            try:
                flujo.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(1)
