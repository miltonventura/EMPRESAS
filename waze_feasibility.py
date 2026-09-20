#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
waze_feasibility.py — ¿Se pueden descargar datos de empresas / restaurantes /
otras categorías desde Waze?

Este script NO es un scraper de producción: es una herramienta de EVALUACIÓN.
Sondea los endpoints públicos y semipúblicos que usa waze.com, mide qué
devuelven realmente (campos, categorías, cobertura, límites) y emite un
veredicto razonado, junto con las implicaciones legales y las alternativas
oficiales.

Uso típico:

    python3 waze_feasibility.py --ciudad "Ciudad de Mexico" --lat 19.4326 --lon -99.1332
    python3 waze_feasibility.py --lat 19.4326 --lon -99.1332 --json informe.json --markdown informe.md
    python3 waze_feasibility.py --self-test          # sin red, valida la lógica de parseo
    python3 waze_feasibility.py --solo-legal         # sin red, solo el análisis de viabilidad legal

Códigos de salida:
    0 = viable          (al menos un endpoint entrega negocios con categoría)
    1 = parcial         (hay datos, pero incompletos o sin categoría)
    2 = no viable       (todo bloqueado / vacío / requiere credenciales)
    3 = error de uso

Sin dependencias externas: solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

__version__ = "1.0.0"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 waze-feasibility-probe/" + __version__
)

# Entornos de Waze: la API se sirve desde clusters regionales distintos.
ENTORNOS = {
    "row": "Resto del mundo (Europa, LATAM, Asia)",
    "na": "Norteamérica (EE. UU., Canadá)",
    "il": "Israel",
}

# Categorías a probar. La clave es la etiqueta del informe; el valor son los
# términos de búsqueda que se mandan al buscador de Waze.
CATEGORIAS_DEFECTO: dict[str, list[str]] = {
    "restaurantes": ["restaurante", "restaurant"],
    "cafeterias": ["cafeteria", "cafe"],
    "gasolineras": ["gasolinera", "gas station"],
    "supermercados": ["supermercado", "supermarket"],
    "farmacias": ["farmacia", "pharmacy"],
    "hoteles": ["hotel"],
    "bancos": ["banco", "bank"],
    "hospitales": ["hospital"],
    "talleres": ["taller mecanico", "car repair"],
    "empresas_generico": ["oficinas", "empresa"],
}

# Claves JSON que delatan cada tipo de dato dentro de una respuesta desconocida.
CLAVES_LAT = ("lat", "latitude", "y")
CLAVES_LON = ("lon", "lng", "longitude", "x")
CLAVES_NOMBRE = ("name", "title", "venuename", "label", "text")
CLAVES_CATEGORIA = ("categories", "category", "categoria", "types", "type", "subcategories")
CLAVES_DIRECCION = ("address", "street", "city", "housenumber", "state", "country", "formattedaddress")
CLAVES_ID = ("venueid", "id", "placeid", "uuid", "segmentid")


# --------------------------------------------------------------------------- #
# Modelo de datos
# --------------------------------------------------------------------------- #

@dataclass
class Resultado:
    """Resultado de sondear un endpoint concreto."""
    endpoint: str
    descripcion: str
    url: str
    ok: bool = False
    status: int | None = None
    error: str | None = None
    ms: int = 0
    content_type: str = ""
    bytes: int = 0
    registros: int = 0
    campos_detectados: dict[str, bool] = field(default_factory=dict)
    muestra: Any = None
    robots_permitido: bool | None = None
    requiere_credenciales: bool = False
    veredicto: str = "no_evaluado"
    notas: list[str] = field(default_factory=list)


@dataclass
class Informe:
    generado: str
    version: str
    entorno_waze: str
    ubicacion: dict[str, Any]
    robots: dict[str, Any] = field(default_factory=dict)
    endpoints: list[Resultado] = field(default_factory=list)
    cobertura_categorias: dict[str, Any] = field(default_factory=dict)
    veredicto_tecnico: str = "no_evaluado"
    veredicto_legal: str = ""
    alternativas: list[dict[str, str]] = field(default_factory=list)
    resumen: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Capa HTTP (stdlib, con reintentos y control de ritmo)
# --------------------------------------------------------------------------- #

class Cliente:
    """Cliente HTTP mínimo: timeouts, reintentos con backoff y rate limiting."""

    def __init__(self, timeout: float = 15.0, reintentos: int = 2,
                 delay: float = 1.5, verificar_tls: bool = True,
                 verbose: bool = False):
        self.timeout = timeout
        self.reintentos = reintentos
        self.delay = delay
        self.verbose = verbose
        self._ultimo = 0.0
        self._ctx = ssl.create_default_context()
        if not verificar_tls:
            # Solo para depurar detrás de proxies corporativos que reescriben TLS.
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    def _esperar_turno(self) -> None:
        transcurrido = time.monotonic() - self._ultimo
        if transcurrido < self.delay:
            time.sleep(self.delay - transcurrido)
        self._ultimo = time.monotonic()

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int | None, bytes, str, str | None]:
        """Devuelve (status, cuerpo, content_type, error)."""
        cabeceras = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": "https://www.waze.com/es/live-map",
        }
        cabeceras.update(headers or {})

        ultimo_error: str | None = None
        for intento in range(self.reintentos + 1):
            self._esperar_turno()
            if self.verbose:
                print(f"    GET {url}", file=sys.stderr)
            req = urllib.request.Request(url, headers=cabeceras, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    cuerpo = resp.read(2_000_000)  # tope defensivo: 2 MB
                    return resp.status, cuerpo, resp.headers.get("Content-Type", ""), None
            except urllib.error.HTTPError as e:
                cuerpo = b""
                try:
                    cuerpo = e.read(200_000)
                except Exception:  # noqa: BLE001 - el cuerpo del error es opcional
                    pass
                # 4xx no se reintenta: la respuesta ya es informativa.
                if 400 <= e.code < 500 and e.code not in (408, 429):
                    return e.code, cuerpo, e.headers.get("Content-Type", "") if e.headers else "", None
                ultimo_error = f"HTTP {e.code} {e.reason}"
            except urllib.error.URLError as e:
                ultimo_error = f"URLError: {e.reason}"
            except (socket.timeout, TimeoutError):
                ultimo_error = f"timeout tras {self.timeout}s"
            except Exception as e:  # noqa: BLE001 - la sonda nunca debe abortar
                ultimo_error = f"{type(e).__name__}: {e}"

            if intento < self.reintentos:
                time.sleep(2 ** intento)  # backoff 1s, 2s, 4s...

        return None, b"", "", ultimo_error


# --------------------------------------------------------------------------- #
# Análisis genérico de respuestas (no asumimos el esquema de Waze)
# --------------------------------------------------------------------------- #

def _normaliza(clave: str) -> str:
    return re.sub(r"[^a-z]", "", clave.lower())


def extraer_registros(obj: Any, profundidad: int = 0) -> list[dict]:
    """Recorre un JSON arbitrario y devuelve los dicts que parecen lugares.

    Un "lugar" es cualquier dict con coordenadas o con nombre + dirección.
    Deliberadamente tolerante: los esquemas de Waze cambian sin aviso y el
    objetivo del script es descubrirlos, no darlos por supuestos.
    """
    if profundidad > 8:
        return []

    encontrados: list[dict] = []
    if isinstance(obj, dict):
        claves = {_normaliza(k) for k in obj}
        tiene_coords = bool(claves & set(CLAVES_LAT)) and bool(claves & set(CLAVES_LON))
        tiene_coords = tiene_coords or any(
            isinstance(v, dict) and {_normaliza(k) for k in v} & set(CLAVES_LAT)
            for k, v in obj.items() if _normaliza(k) in ("location", "geometry", "position", "coords")
        )
        tiene_nombre = bool(claves & set(CLAVES_NOMBRE))
        tiene_direccion = bool(claves & set(CLAVES_DIRECCION))
        if tiene_coords or (tiene_nombre and tiene_direccion):
            encontrados.append(obj)
        else:
            for v in obj.values():
                encontrados.extend(extraer_registros(v, profundidad + 1))
    elif isinstance(obj, list):
        for v in obj:
            encontrados.extend(extraer_registros(v, profundidad + 1))
    return encontrados


def detectar_campos(registros: Iterable[dict]) -> dict[str, bool]:
    """Qué campos de interés comercial aparecen en la muestra."""
    presentes = {"nombre": False, "coordenadas": False, "direccion": False,
                 "categoria": False, "identificador": False}
    for reg in registros:
        claves = set()

        def _recoge(d: Any, nivel: int = 0) -> None:
            if nivel > 3 or not isinstance(d, dict):
                return
            for k, v in d.items():
                claves.add(_normaliza(k))
                if isinstance(v, dict):
                    _recoge(v, nivel + 1)

        _recoge(reg)
        presentes["nombre"] |= bool(claves & set(CLAVES_NOMBRE))
        presentes["coordenadas"] |= bool(claves & set(CLAVES_LAT)) and bool(claves & set(CLAVES_LON))
        presentes["direccion"] |= bool(claves & set(CLAVES_DIRECCION))
        presentes["categoria"] |= bool(claves & set(CLAVES_CATEGORIA))
        presentes["identificador"] |= bool(claves & set(CLAVES_ID))
    return presentes


def recorta(obj: Any, max_items: int = 2, max_texto: int = 400) -> Any:
    """Muestra abreviada para que el informe no pese megabytes."""
    if isinstance(obj, list):
        return [recorta(x, max_items, max_texto) for x in obj[:max_items]]
    if isinstance(obj, dict):
        return {k: recorta(v, max_items, max_texto) for k, v in list(obj.items())[:20]}
    if isinstance(obj, str) and len(obj) > max_texto:
        return obj[:max_texto] + "…"
    return obj


# --------------------------------------------------------------------------- #
# Definición de los endpoints a sondear
# --------------------------------------------------------------------------- #

def construir_endpoints(env: str, lat: float, lon: float, radio_km: float,
                        consulta: str, lang: str) -> list[dict[str, Any]]:
    """Catálogo de endpoints conocidos de Waze, parametrizados."""
    # El prefijo del SearchServer depende del cluster regional.
    prefijo = {"row": "row-", "na": "", "il": "il-"}.get(env, "row-")
    # ~111 km por grado de latitud; corregimos la longitud por el coseno.
    import math
    dlat = radio_km / 111.0
    dlon = radio_km / max(1e-6, 111.0 * math.cos(math.radians(lat)))
    top, bottom = lat + dlat, lat - dlat
    left, right = lon - dlon, lon + dlon

    q = urllib.parse.quote(consulta)

    return [
        {
            "nombre": "livemap_autocomplete",
            "descripcion": "Autocompletado del buscador del Live Map (sugiere lugares y negocios).",
            "url": (f"https://www.waze.com/live-map/api/autocomplete"
                    f"?q={q}&exp=8,10,12&geo-env={env}&v=-1&lang={lang}"
                    f"&lat={lat}&lon={lon}"),
            "espera": "negocios",
        },
        {
            "nombre": "searchserver_mozi",
            "descripcion": "Buscador de lugares 'mozi' que alimenta al Live Map (nombre, calle, ciudad, coords).",
            "url": (f"https://www.waze.com/{prefijo}SearchServer/mozi"
                    f"?q={q}&lang={lang}&origin=livemap&lat={lat}&lon={lon}"),
            "espera": "negocios",
        },
        {
            "nombre": "livemap_venues_bbox",
            "descripcion": "Lugares (venues) dentro de un recuadro geográfico del Live Map.",
            "url": (f"https://www.waze.com/live-map/api/venues"
                    f"?top={top}&bottom={bottom}&left={left}&right={right}&env={env}"),
            "espera": "negocios",
        },
        {
            "nombre": "livemap_georss",
            "descripcion": "Feed de tráfico: alertas y atascos en un recuadro. NO contiene negocios.",
            "url": (f"https://www.waze.com/live-map/api/georss"
                    f"?top={top}&bottom={bottom}&left={left}&right={right}"
                    f"&env={env}&types=alerts,traffic"),
            "espera": "trafico",
        },
        {
            "nombre": "wme_venues",
            "descripcion": "API del Waze Map Editor (WME): datos de edición del mapa. Requiere sesión iniciada.",
            "url": (f"https://www.waze.com/api/venues"
                    f"?bbox={left},{bottom},{right},{top}&env={env}"),
            "espera": "negocios",
            "requiere_credenciales": True,
        },
        {
            "nombre": "wfc_ccp",
            "descripcion": "Waze for Cities (CCP): feed oficial para gobiernos. Solo tráfico/incidencias, con token.",
            "url": "https://www.waze.com/row-partnerhub-api/feeds/?format=json",
            "espera": "trafico",
            "requiere_credenciales": True,
        },
    ]


# --------------------------------------------------------------------------- #
# Sondeo
# --------------------------------------------------------------------------- #

def comprobar_robots(cliente: Cliente, urls: list[str]) -> tuple[dict[str, Any], dict[str, bool]]:
    """Lee https://www.waze.com/robots.txt y evalúa cada ruta."""
    status, cuerpo, _, error = cliente.get("https://www.waze.com/robots.txt")
    info: dict[str, Any] = {"status": status, "error": error, "reglas": None}
    permisos: dict[str, bool] = {}

    if status != 200 or not cuerpo:
        info["nota"] = "No se pudo leer robots.txt; se asume desconocido (no se asume permiso)."
        return info, {u: None for u in urls}  # type: ignore[misc]

    texto = cuerpo.decode("utf-8", "replace")
    info["reglas"] = texto[:2000]
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(texto.splitlines())
    for u in urls:
        try:
            permisos[u] = parser.can_fetch(UA, u)
        except Exception:  # noqa: BLE001
            permisos[u] = None  # type: ignore[assignment]
    return info, permisos


def sondear(cliente: Cliente, spec: dict[str, Any], robots_ok: bool | None,
            respetar_robots: bool) -> Resultado:
    r = Resultado(endpoint=spec["nombre"], descripcion=spec["descripcion"], url=spec["url"])
    r.robots_permitido = robots_ok
    r.requiere_credenciales = bool(spec.get("requiere_credenciales"))

    if respetar_robots and robots_ok is False:
        r.veredicto = "omitido_por_robots"
        r.notas.append("robots.txt no permite esta ruta para nuestro user-agent; no se solicitó.")
        return r

    t0 = time.monotonic()
    status, cuerpo, ctype, error = cliente.get(spec["url"])
    r.ms = int((time.monotonic() - t0) * 1000)
    r.status, r.content_type, r.bytes, r.error = status, ctype or "", len(cuerpo), error

    if error or status is None:
        r.veredicto = "inalcanzable"
        r.notas.append(f"Sin respuesta: {error}")
        return r

    if status in (401, 403):
        r.veredicto = "bloqueado"
        r.notas.append(f"HTTP {status}: requiere autenticación o el servidor rechaza clientes automatizados.")
        return r
    if status == 429:
        r.veredicto = "limitado_por_ritmo"
        r.notas.append("HTTP 429: límite de peticiones. Habría que bajar el ritmo (--delay).")
        return r
    if status >= 400:
        r.veredicto = "no_disponible"
        r.notas.append(f"HTTP {status}: el endpoint no existe o cambió de forma.")
        return r

    r.ok = True
    texto = cuerpo.decode("utf-8", "replace")

    if "json" not in (ctype or "").lower() and not texto.lstrip()[:1] in ("{", "["):
        r.veredicto = "html_no_datos"
        r.notas.append("La respuesta no es JSON (probablemente HTML o un muro anti-bot).")
        r.muestra = texto[:400]
        return r

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        r.veredicto = "json_invalido"
        r.notas.append(f"JSON ilegible: {e}")
        r.muestra = texto[:400]
        return r

    registros = extraer_registros(datos)
    r.registros = len(registros)
    r.campos_detectados = detectar_campos(registros[:50])
    r.muestra = recorta(registros[:2] if registros else datos)

    if not registros:
        r.veredicto = "vacio"
        r.notas.append("Respondió 200 pero no se reconocieron registros de lugares.")
    elif spec.get("espera") == "trafico":
        r.veredicto = "solo_trafico"
        r.notas.append("Devuelve incidencias/tráfico, no fichas de negocio.")
    elif r.campos_detectados.get("categoria"):
        r.veredicto = "viable"
        r.notas.append("Devuelve lugares con categoría: sirve para clasificar por rubro.")
    else:
        r.veredicto = "parcial"
        r.notas.append("Devuelve lugares pero sin campo de categoría fiable; habría que inferir el rubro.")
    return r


def probar_categorias(cliente: Cliente, env: str, lat: float, lon: float, lang: str,
                      categorias: dict[str, list[str]], endpoint_nombre: str,
                      limite: int | None) -> dict[str, Any]:
    """Mide cuántos resultados devuelve el mejor endpoint por cada categoría."""
    salida: dict[str, Any] = {"endpoint": endpoint_nombre, "por_categoria": {}}
    items = list(categorias.items())
    if limite:
        items = items[:limite]

    for etiqueta, terminos in items:
        detalle = {"terminos": terminos, "resultados": 0, "status": None, "ejemplos": []}
        for termino in terminos:
            specs = construir_endpoints(env, lat, lon, 5.0, termino, lang)
            spec = next((s for s in specs if s["nombre"] == endpoint_nombre), None)
            if spec is None:
                break
            status, cuerpo, _, error = cliente.get(spec["url"])
            detalle["status"] = status or error
            if status == 200:
                try:
                    regs = extraer_registros(json.loads(cuerpo.decode("utf-8", "replace")))
                except json.JSONDecodeError:
                    regs = []
                if regs:
                    detalle["resultados"] = len(regs)
                    detalle["ejemplos"] = [
                        str(reg.get("name") or reg.get("title") or "")[:80]
                        for reg in regs[:3]
                    ]
                    break  # ya tenemos señal con este término
        salida["por_categoria"][etiqueta] = detalle
    return salida


# --------------------------------------------------------------------------- #
# Análisis legal y alternativas (independiente de la red)
# --------------------------------------------------------------------------- #

TEXTO_LEGAL = """\
Lo técnico no decide lo legal. Aunque una sonda responda 200, estos endpoints
son APIs internas del Live Map, no una API pública documentada:

1. Los Términos de Servicio de Waze (y los de Google, su propietaria) prohíben
   el acceso automatizado, el scraping y la extracción masiva o la reutilización
   de contenido del servicio sin autorización escrita.
2. No hay API pública de "lugares/negocios" de Waze. Los endpoints que usa el
   Live Map no están versionados ni documentados: pueden cambiar o cerrarse sin
   aviso, y suelen aplicar bloqueo por IP ante tráfico sostenido.
3. Buena parte de las fichas de negocio en Waze provienen de aportaciones de la
   comunidad (Waze Map Editor) y de proveedores externos; redistribuir ese
   contenido puede vulnerar derechos de terceros además del contrato con Waze.
4. Si los registros incluyen datos de personas (negocios unipersonales,
   teléfonos, nombres), aplica normativa de protección de datos (RGPD/LFPDPPP
   según jurisdicción) aunque el dato sea "público".

Conclusión legal: para un uso comercial o sistemático, el scraping del Live Map
NO es una vía defendible. Para una prueba puntual y de bajo volumen es
técnicamente posible, pero sigue siendo contrario a los ToS.
"""

ALTERNATIVAS = [
    {"nombre": "Waze for Cities (CCP)",
     "que_da": "Tráfico, atascos, incidencias y cierres. NO listados de negocios.",
     "acceso": "Gratuito para entidades públicas, previo convenio. Requiere token.",
     "url": "https://www.waze.com/es/wazeforcities"},
    {"nombre": "Waze Ads / Waze Local",
     "que_da": "Gestión y alta de TU propio negocio en el mapa (no descarga masiva).",
     "acceso": "Cuenta de anunciante.",
     "url": "https://www.waze.com/es/business"},
    {"nombre": "Google Places API (New)",
     "que_da": "Negocios con nombre, dirección, categoría, horarios, reseñas. Es la fuente que más se parece a lo que se busca en Waze.",
     "acceso": "API de pago con clave; permite uso comercial dentro de sus términos.",
     "url": "https://developers.google.com/maps/documentation/places/web-service"},
    {"nombre": "OpenStreetMap / Overpass API",
     "que_da": "POIs con categoría (amenity=restaurant, shop=*, office=*). Descarga masiva permitida.",
     "acceso": "Gratuito, licencia ODbL (exige atribución y compartir igual).",
     "url": "https://overpass-api.de/"},
    {"nombre": "Foursquare Places / OS Places",
     "que_da": "Catálogo de lugares con categorías normalizadas y dataset descargable.",
     "acceso": "Gratuito con límites / dataset abierto.",
     "url": "https://location.foursquare.com/products/places-api/"},
    {"nombre": "HERE Places / TomTom Search",
     "que_da": "POIs comerciales con categorías, orientado a automoción.",
     "acceso": "API de pago con capa gratuita.",
     "url": "https://developer.here.com/"},
    {"nombre": "Registros mercantiles oficiales / INEGI DENUE (MX)",
     "que_da": "Empresas con razón social, giro (SCIAN), domicilio y tamaño. Datos abiertos.",
     "acceso": "Descarga libre.",
     "url": "https://www.inegi.org.mx/app/mapa/denue/"},
]


# --------------------------------------------------------------------------- #
# Informe
# --------------------------------------------------------------------------- #

def calcular_veredicto(resultados: list[Resultado]) -> tuple[str, list[str]]:
    resumen: list[str] = []
    viables = [r for r in resultados if r.veredicto == "viable"]
    parciales = [r for r in resultados if r.veredicto == "parcial"]
    trafico = [r for r in resultados if r.veredicto == "solo_trafico"]
    bloqueados = [r for r in resultados if r.veredicto in ("bloqueado", "limitado_por_ritmo", "omitido_por_robots")]

    if viables:
        veredicto = "viable"
        resumen.append(
            f"Técnicamente SÍ: {len(viables)} endpoint(s) devuelven negocios con categoría "
            f"({', '.join(r.endpoint for r in viables)}).")
    elif parciales:
        veredicto = "parcial"
        resumen.append(
            f"Parcialmente: {len(parciales)} endpoint(s) devuelven lugares, pero sin categoría "
            f"utilizable ({', '.join(r.endpoint for r in parciales)}). Habría que inferir el rubro.")
    else:
        veredicto = "no_viable"
        resumen.append("Técnicamente NO: ningún endpoint devolvió fichas de negocio explotables.")

    if trafico:
        resumen.append(
            f"{len(trafico)} endpoint(s) solo exponen tráfico/incidencias: el dato fuerte de Waze "
            "es la movilidad, no el directorio de empresas.")
    if bloqueados:
        resumen.append(
            f"{len(bloqueados)} endpoint(s) bloqueados o restringidos "
            f"({', '.join(r.endpoint for r in bloqueados)}).")
    resumen.append(
        "En todos los casos, el acceso automatizado al Live Map contraviene los Términos de "
        "Servicio de Waze: ver la sección legal antes de construir nada encima.")
    return veredicto, resumen


def imprimir_consola(inf: Informe) -> None:
    def linea(c: str = "─") -> None:
        print(c * 78)

    linea("═")
    print(" EVALUACIÓN: ¿se pueden descargar datos de empresas desde Waze?")
    linea("═")
    print(f" Fecha:     {inf.generado}")
    print(f" Entorno:   {inf.entorno_waze} — {ENTORNOS.get(inf.entorno_waze, 'desconocido')}")
    loc = inf.ubicacion
    print(f" Ubicación: {loc.get('ciudad') or '(sin nombre)'} "
          f"lat={loc.get('lat')} lon={loc.get('lon')} radio={loc.get('radio_km')} km")
    print()

    if inf.robots:
        estado = inf.robots.get("status")
        print(f" robots.txt: HTTP {estado}" + (f" — {inf.robots.get('nota', '')}" if inf.robots.get("nota") else ""))
        print()

    linea()
    print(" ENDPOINTS SONDEADOS")
    linea()
    for r in inf.endpoints:
        marca = {"viable": "✔", "parcial": "~", "solo_trafico": "≈"}.get(r.veredicto, "✘")
        print(f" {marca} {r.endpoint:<24} [{r.veredicto}]")
        print(f"   {r.descripcion}")
        detalles = [f"HTTP {r.status}" if r.status else "sin respuesta", f"{r.ms} ms",
                    f"{r.bytes} B", f"{r.registros} registros"]
        if r.requiere_credenciales:
            detalles.append("requiere credenciales")
        if r.robots_permitido is False:
            detalles.append("robots: prohibido")
        print(f"   {' | '.join(detalles)}")
        if r.campos_detectados:
            campos = ", ".join(k for k, v in r.campos_detectados.items() if v) or "ninguno"
            print(f"   campos: {campos}")
        for n in r.notas:
            print(f"   · {n}")
        print()

    if inf.cobertura_categorias.get("por_categoria"):
        linea()
        print(f" COBERTURA POR CATEGORÍA (endpoint: {inf.cobertura_categorias.get('endpoint')})")
        linea()
        for etiqueta, d in inf.cobertura_categorias["por_categoria"].items():
            ejemplos = "; ".join(x for x in d.get("ejemplos", []) if x)
            print(f" {etiqueta:<20} {d.get('resultados', 0):>4} resultados  "
                  f"(status {d.get('status')})" + (f"  → {ejemplos}" if ejemplos else ""))
        print()

    linea()
    print(" VEREDICTO TÉCNICO: " + inf.veredicto_tecnico.upper())
    linea()
    for s in inf.resumen:
        print(f" • {s}")
    print()

    linea()
    print(" VIABILIDAD LEGAL")
    linea()
    print(inf.veredicto_legal)

    linea()
    print(" ALTERNATIVAS RECOMENDADAS")
    linea()
    for a in inf.alternativas:
        print(f" • {a['nombre']}")
        print(f"     qué da: {a['que_da']}")
        print(f"     acceso: {a['acceso']}")
        print(f"     {a['url']}")
    print()


def a_markdown(inf: Informe) -> str:
    out: list[str] = []
    out.append("# Evaluación: descarga de datos de empresas desde Waze\n")
    out.append(f"- **Generado:** {inf.generado}")
    out.append(f"- **Entorno Waze:** `{inf.entorno_waze}` ({ENTORNOS.get(inf.entorno_waze, '?')})")
    loc = inf.ubicacion
    out.append(f"- **Ubicación de prueba:** {loc.get('ciudad') or '—'} "
               f"(`{loc.get('lat')}`, `{loc.get('lon')}`), radio {loc.get('radio_km')} km")
    out.append(f"- **Veredicto técnico:** `{inf.veredicto_tecnico}`\n")

    out.append("## Endpoints sondeados\n")
    out.append("| Endpoint | Veredicto | HTTP | ms | Registros | Campos |")
    out.append("|---|---|---|---|---|---|")
    for r in inf.endpoints:
        campos = ", ".join(k for k, v in r.campos_detectados.items() if v) or "—"
        out.append(f"| `{r.endpoint}` | {r.veredicto} | {r.status or '—'} | {r.ms} | {r.registros} | {campos} |")
    out.append("")

    for r in inf.endpoints:
        out.append(f"### `{r.endpoint}`\n")
        out.append(f"{r.descripcion}\n")
        out.append(f"- URL: `{r.url}`")
        for n in r.notas:
            out.append(f"- {n}")
        if r.muestra is not None:
            muestra = json.dumps(r.muestra, ensure_ascii=False, indent=2)[:1500]
            out.append(f"\n```json\n{muestra}\n```\n")

    if inf.cobertura_categorias.get("por_categoria"):
        out.append("## Cobertura por categoría\n")
        out.append("| Categoría | Resultados | Status | Ejemplos |")
        out.append("|---|---|---|---|")
        for etiqueta, d in inf.cobertura_categorias["por_categoria"].items():
            ejemplos = "; ".join(x for x in d.get("ejemplos", []) if x) or "—"
            out.append(f"| {etiqueta} | {d.get('resultados', 0)} | {d.get('status')} | {ejemplos} |")
        out.append("")

    out.append("## Resumen\n")
    for s in inf.resumen:
        out.append(f"- {s}")
    out.append("\n## Viabilidad legal\n")
    out.append(inf.veredicto_legal)
    out.append("\n## Alternativas recomendadas\n")
    out.append("| Fuente | Qué entrega | Acceso |")
    out.append("|---|---|---|")
    for a in inf.alternativas:
        out.append(f"| [{a['nombre']}]({a['url']}) | {a['que_da']} | {a['acceso']} |")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Self-test offline: valida el análisis sin tocar la red
# --------------------------------------------------------------------------- #

FIXTURES: dict[str, Any] = {
    "mozi_con_categoria": [
        {"name": "Taquería El Califa", "venueId": "abc-123",
         "location": {"lat": 19.4201, "lon": -99.1712},
         "street": "Av. Insurgentes Sur", "city": "Ciudad de México",
         "categories": ["RESTAURANT"], "provider": "waze"},
        {"name": "Cafebrería El Péndulo", "venueId": "def-456",
         "location": {"lat": 19.4113, "lon": -99.1698},
         "street": "Álvaro Obregón", "city": "Ciudad de México",
         "categories": ["CAFE_HOUSE"], "provider": "waze"},
    ],
    "sin_categoria": {"results": [
        {"title": "Calle Madero", "lat": 19.4335, "lng": -99.1380, "address": "Centro"},
    ]},
    "solo_trafico": {"alerts": [
        {"type": "JAM", "location": {"x": -99.13, "y": 19.43}, "street": "Viaducto", "reportRating": 4},
    ]},
    "vacio": {"results": [], "totalResults": 0},
}


def self_test() -> int:
    print("Self-test offline (sin red) — validando el análisis de respuestas\n")
    fallos = 0

    casos = [
        ("mozi_con_categoria", 2, {"nombre", "coordenadas", "direccion", "categoria", "identificador"}),
        ("sin_categoria", 1, {"nombre", "coordenadas", "direccion"}),
        ("solo_trafico", 1, {"coordenadas", "direccion"}),
        ("vacio", 0, set()),
    ]
    for clave, esperados, campos_esperados in casos:
        regs = extraer_registros(FIXTURES[clave])
        campos = {k for k, v in detectar_campos(regs).items() if v}
        ok_n = len(regs) == esperados
        ok_c = campos_esperados.issubset(campos) if campos_esperados else not campos
        estado = "OK " if (ok_n and ok_c) else "FALLO"
        if not (ok_n and ok_c):
            fallos += 1
        print(f" [{estado}] {clave:<22} registros={len(regs)} (esperado {esperados}) campos={sorted(campos)}")

    # Construcción de URLs y veredicto global.
    specs = construir_endpoints("row", 19.4326, -99.1332, 5.0, "restaurante", "es")
    ok_urls = len(specs) == 6 and all(s["url"].startswith("https://www.waze.com/") for s in specs)
    print(f" [{'OK ' if ok_urls else 'FALLO'}] construir_endpoints      {len(specs)} endpoints, URLs válidas={ok_urls}")
    fallos += 0 if ok_urls else 1

    simulado = [
        Resultado(endpoint="a", descripcion="", url="", veredicto="viable"),
        Resultado(endpoint="b", descripcion="", url="", veredicto="solo_trafico"),
    ]
    veredicto, _ = calcular_veredicto(simulado)
    ok_v = veredicto == "viable"
    print(f" [{'OK ' if ok_v else 'FALLO'}] calcular_veredicto       -> {veredicto}")
    fallos += 0 if ok_v else 1

    print(f"\n{'Todo correcto.' if not fallos else str(fallos) + ' fallo(s).'}")
    return 0 if fallos == 0 else 2


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="waze_feasibility.py",
        description="Evalúa si es posible descargar datos de empresas, restaurantes y otras "
                    "categorías desde Waze, y con qué implicaciones.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Herramienta de evaluación, no de extracción masiva. Lee la sección legal.",
    )
    p.add_argument("--lat", type=float, default=19.4326, help="Latitud del punto de prueba (def: CDMX).")
    p.add_argument("--lon", type=float, default=-99.1332, help="Longitud del punto de prueba (def: CDMX).")
    p.add_argument("--ciudad", default="Ciudad de México", help="Nombre de la ciudad, solo para el informe.")
    p.add_argument("--radio-km", type=float, default=5.0, help="Radio del recuadro de búsqueda (def: 5).")
    p.add_argument("--env", choices=sorted(ENTORNOS), default="row", help="Cluster regional de Waze (def: row).")
    p.add_argument("--lang", default="es", help="Idioma de la consulta (def: es).")
    p.add_argument("--consulta", default="restaurante", help="Término de la sonda inicial.")
    p.add_argument("--categorias", type=int, default=6, metavar="N",
                   help="Cuántas categorías probar en el test de cobertura (0 = ninguna).")
    p.add_argument("--delay", type=float, default=1.5, help="Segundos entre peticiones (def: 1.5).")
    p.add_argument("--timeout", type=float, default=15.0, help="Timeout por petición (def: 15).")
    p.add_argument("--reintentos", type=int, default=2, help="Reintentos ante fallo de red (def: 2).")
    p.add_argument("--ignorar-robots", action="store_true",
                   help="Sondear aunque robots.txt lo desaconseje (no recomendado).")
    p.add_argument("--sin-verificar-tls", action="store_true", help="Desactiva la verificación TLS (solo depuración).")
    p.add_argument("--json", metavar="ARCHIVO", help="Guarda el informe completo en JSON.")
    p.add_argument("--markdown", metavar="ARCHIVO", help="Guarda el informe en Markdown.")
    p.add_argument("--solo-legal", action="store_true", help="No toca la red: solo análisis legal y alternativas.")
    p.add_argument("--self-test", action="store_true", help="No toca la red: valida la lógica interna.")
    p.add_argument("-v", "--verbose", action="store_true", help="Traza cada petición por stderr.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if args.self_test:
        return self_test()

    inf = Informe(
        generado=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        version=__version__,
        entorno_waze=args.env,
        ubicacion={"ciudad": args.ciudad, "lat": args.lat, "lon": args.lon, "radio_km": args.radio_km},
        veredicto_legal=TEXTO_LEGAL,
        alternativas=ALTERNATIVAS,
    )

    if args.solo_legal:
        inf.veredicto_tecnico = "no_evaluado"
        inf.resumen = ["Modo --solo-legal: no se sondeó la red."]
        imprimir_consola(inf)
        return 1

    cliente = Cliente(timeout=args.timeout, reintentos=args.reintentos, delay=args.delay,
                      verificar_tls=not args.sin_verificar_tls, verbose=args.verbose)

    specs = construir_endpoints(args.env, args.lat, args.lon, args.radio_km, args.consulta, args.lang)

    print("Leyendo robots.txt de waze.com…", file=sys.stderr)
    inf.robots, permisos = comprobar_robots(cliente, [s["url"] for s in specs])

    print(f"Sondeando {len(specs)} endpoints…", file=sys.stderr)
    for spec in specs:
        print(f"  → {spec['nombre']}", file=sys.stderr)
        inf.endpoints.append(
            sondear(cliente, spec, permisos.get(spec["url"]), respetar_robots=not args.ignorar_robots)
        )

    # El test de cobertura solo tiene sentido sobre un endpoint que devolvió lugares.
    mejor = next((r for r in inf.endpoints if r.veredicto == "viable"), None) \
        or next((r for r in inf.endpoints if r.veredicto == "parcial"), None)
    if mejor and args.categorias > 0:
        print(f"Probando cobertura por categoría sobre '{mejor.endpoint}'…", file=sys.stderr)
        inf.cobertura_categorias = probar_categorias(
            cliente, args.env, args.lat, args.lon, args.lang,
            CATEGORIAS_DEFECTO, mejor.endpoint, args.categorias,
        )
    elif args.categorias > 0:
        inf.cobertura_categorias = {
            "endpoint": None,
            "nota": "Omitido: ningún endpoint devolvió lugares sobre los que medir cobertura.",
            "por_categoria": {},
        }

    inf.veredicto_tecnico, inf.resumen = calcular_veredicto(inf.endpoints)
    imprimir_consola(inf)

    if args.json:
        payload = asdict(inf)
        payload["endpoints"] = [asdict(r) for r in inf.endpoints]
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"Informe JSON escrito en {args.json}", file=sys.stderr)

    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(a_markdown(inf))
        print(f"Informe Markdown escrito en {args.markdown}", file=sys.stderr)

    return {"viable": 0, "parcial": 1}.get(inf.veredicto_tecnico, 2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.", file=sys.stderr)
        sys.exit(130)
