#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta y descarga de registros de empresas en Google Maps.

Utiliza la Places API (New) de Google (endpoint `places:searchText`) para
recorrer un area geografica en celdas (grilla) y recolectar los negocios
registrados, con deduplicacion por `place id` y exportacion a CSV / JSON /
XLSX / GeoJSON.

Por defecto busca en el distrito de San Salvador (El Salvador).

Uso rapido
----------
    export GOOGLE_MAPS_API_KEY="tu_api_key"
    python buscar_empresas.py                      # busqueda completa por defecto
    python buscar_empresas.py --dry-run            # estimar peticiones y costo
    python buscar_empresas.py --categorias "restaurante,farmacia" --paso 800
    python buscar_empresas.py --distrito "San Salvador, Cusco, Peru" --region PE

Requisitos
----------
    pip install -r requirements.txt
    APIs habilitadas en Google Cloud: "Places API (New)" y (opcional para
    resolver automaticamente los limites del distrito) "Geocoding API".
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Falta la dependencia 'requests'. Instalala con: pip install -r requirements.txt")


# --------------------------------------------------------------------------- #
# Configuracion general
# --------------------------------------------------------------------------- #

PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Campos solicitados a la API. Cada campo extra puede cambiar el SKU facturado,
# por eso se pide solo lo necesario para un registro de empresa util.
CAMPOS_LUGAR = [
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.shortFormattedAddress",
    "places.addressComponents",
    "places.location",
    "places.plusCode",
    "places.types",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
    "places.businessStatus",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.regularOpeningHours",
]
FIELD_MASK = ",".join(CAMPOS_LUGAR + ["nextPageToken"])

# Limites aproximados del distrito de San Salvador, El Salvador.
# Se usan solo si no se puede geocodificar (Geocoding API deshabilitada, etc.).
BBOX_SAN_SALVADOR = {
    "sur": 13.6450,
    "oeste": -89.2700,
    "norte": 13.7500,
    "este": -89.1500,
}

# Categorias de negocio consultadas por celda. Cada una es una peticion de
# texto independiente; recortar la lista reduce costo y tiempo.
CATEGORIAS_POR_DEFECTO = [
    "empresa",
    "oficina corporativa",
    "tienda",
    "supermercado",
    "restaurante",
    "cafeteria",
    "hotel",
    "farmacia",
    "clinica",
    "hospital",
    "banco",
    "aseguradora",
    "ferreteria",
    "taller mecanico",
    "gasolinera",
    "salon de belleza",
    "gimnasio",
    "libreria",
    "panaderia",
    "tienda de ropa",
    "muebleria",
    "imprenta",
    "consultoria",
    "bufete de abogados",
    "contabilidad",
    "agencia de viajes",
    "escuela",
    "veterinaria",
    "distribuidora",
    "bodega industrial",
]

# Precio orientativo por 1000 peticiones (USD) del SKU Text Search Pro, solo
# para la estimacion de --dry-run. Verifique la tarifa vigente de su cuenta.
COSTO_ESTIMADO_POR_1000 = 32.0

MAX_RESULTADOS_POR_PAGINA = 20
MAX_PAGINAS = 3  # la API entrega como maximo 60 resultados por consulta


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def log(mensaje: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {mensaje}", flush=True)


def normalizar(texto: str) -> str:
    """Minusculas sin acentos, para comparaciones tolerantes."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "")
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.casefold().strip()


def cargar_dotenv(ruta: Path) -> None:
    """Carga variables de un archivo .env sin dependencias externas."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))


def obtener_api_key(valor_cli: str | None) -> str:
    cargar_dotenv(Path(__file__).resolve().parent / ".env")
    api_key = valor_cli or os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "No se encontro la API key.\n"
            "  Defina la variable de entorno GOOGLE_MAPS_API_KEY, cree un archivo .env\n"
            "  (vea .env.example) o pase --api-key <clave>."
        )
    return api_key


# --------------------------------------------------------------------------- #
# Cliente HTTP con reintentos
# --------------------------------------------------------------------------- #

class ClienteGoogle:
    """Envoltura de `requests` con reintentos y control de ritmo."""

    def __init__(self, api_key: str, pausa: float = 0.2, reintentos: int = 4,
                 timeout: int = 30) -> None:
        self.api_key = api_key
        self.pausa = pausa
        self.reintentos = reintentos
        self.timeout = timeout
        self.sesion = requests.Session()
        self.peticiones = 0

    def buscar_texto(self, cuerpo: dict[str, Any]) -> dict[str, Any]:
        cabeceras = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        return self._post(PLACES_SEARCH_TEXT_URL, cuerpo, cabeceras)

    def geocodificar(self, direccion: str, region: str | None) -> dict[str, Any] | None:
        parametros = {"address": direccion, "key": self.api_key, "language": "es"}
        if region:
            parametros["region"] = region.lower()
        try:
            respuesta = self.sesion.get(GEOCODING_URL, params=parametros, timeout=self.timeout)
            respuesta.raise_for_status()
        except requests.RequestException as exc:
            log(f"Aviso: no se pudo geocodificar ({exc}).")
            return None
        datos = respuesta.json()
        if datos.get("status") != "OK" or not datos.get("results"):
            log(f"Aviso: geocodificacion sin resultados (status={datos.get('status')}).")
            return None
        return datos["results"][0]

    def _post(self, url: str, cuerpo: dict[str, Any], cabeceras: dict[str, str]) -> dict[str, Any]:
        espera = 2.0
        for intento in range(1, self.reintentos + 1):
            try:
                respuesta = self.sesion.post(url, json=cuerpo, headers=cabeceras,
                                             timeout=self.timeout)
            except requests.RequestException as exc:
                if intento == self.reintentos:
                    raise
                log(f"Error de red ({exc}); reintento {intento}/{self.reintentos - 1} en {espera:.0f}s.")
                time.sleep(espera)
                espera *= 2
                continue

            self.peticiones += 1

            if respuesta.status_code == 200:
                time.sleep(self.pausa)
                return respuesta.json()

            if respuesta.status_code in (401, 403):
                sys.exit(
                    f"Google rechazo la credencial (HTTP {respuesta.status_code}).\n"
                    f"  Revise que la API key sea valida, que 'Places API (New)' este habilitada\n"
                    f"  y que las restricciones de la clave permitan este uso.\n"
                    f"  Respuesta: {respuesta.text[:500]}"
                )

            if respuesta.status_code == 400:
                texto = respuesta.text
                if "API_KEY" in texto or "API key" in texto:
                    sys.exit(
                        "La API key no es valida (HTTP 400).\n"
                        "  Revise GOOGLE_MAPS_API_KEY / --api-key y que la clave pertenezca a un\n"
                        "  proyecto con 'Places API (New)' habilitada y facturacion activa.\n"
                        f"  Respuesta: {texto[:400]}"
                    )
                sys.exit(f"Peticion invalida (HTTP 400): {texto[:800]}")

            if respuesta.status_code == 429 or respuesta.status_code >= 500:
                if intento == self.reintentos:
                    log(f"Se agotaron los reintentos (HTTP {respuesta.status_code}). Se omite esta consulta.")
                    return {}
                log(f"HTTP {respuesta.status_code}; reintento {intento}/{self.reintentos - 1} en {espera:.0f}s.")
                time.sleep(espera)
                espera *= 2
                continue

            log(f"Respuesta inesperada HTTP {respuesta.status_code}: {respuesta.text[:300]}")
            return {}
        return {}


# --------------------------------------------------------------------------- #
# Geometria: grilla de celdas
# --------------------------------------------------------------------------- #

def resolver_bbox(cliente: ClienteGoogle, distrito: str, region: str | None,
                  bbox_manual: str | None) -> dict[str, float]:
    """Devuelve el rectangulo de busqueda (sur/oeste/norte/este)."""
    if bbox_manual:
        try:
            sur, oeste, norte, este = (float(x) for x in bbox_manual.split(","))
        except ValueError:
            sys.exit("--bbox debe tener el formato: sur,oeste,norte,este")
        return {"sur": sur, "oeste": oeste, "norte": norte, "este": este}

    resultado = cliente.geocodificar(distrito, region)
    if resultado:
        geometria = resultado.get("geometry", {})
        caja = geometria.get("bounds") or geometria.get("viewport")
        if caja:
            log(f"Area resuelta por geocodificacion: {resultado.get('formatted_address')}")
            return {
                "sur": caja["southwest"]["lat"],
                "oeste": caja["southwest"]["lng"],
                "norte": caja["northeast"]["lat"],
                "este": caja["northeast"]["lng"],
            }

    log("Se usan los limites predefinidos del distrito de San Salvador, El Salvador.")
    return dict(BBOX_SAN_SALVADOR)


def generar_celdas(bbox: dict[str, float], paso_metros: float) -> list[dict[str, Any]]:
    """Divide el rectangulo en celdas de aproximadamente `paso_metros` de lado."""
    grados_lat = paso_metros / 111_320.0
    lat_media = (bbox["sur"] + bbox["norte"]) / 2.0
    grados_lon = paso_metros / (111_320.0 * max(math.cos(math.radians(lat_media)), 0.01))

    filas = max(1, math.ceil((bbox["norte"] - bbox["sur"]) / grados_lat))
    columnas = max(1, math.ceil((bbox["este"] - bbox["oeste"]) / grados_lon))

    celdas: list[dict[str, Any]] = []
    for i in range(filas):
        sur = bbox["sur"] + i * grados_lat
        norte = min(sur + grados_lat, bbox["norte"])
        for j in range(columnas):
            oeste = bbox["oeste"] + j * grados_lon
            este = min(oeste + grados_lon, bbox["este"])
            celdas.append({
                "fila": i + 1,
                "columna": j + 1,
                "low": {"latitude": sur, "longitude": oeste},
                "high": {"latitude": norte, "longitude": este},
            })
    return celdas


# --------------------------------------------------------------------------- #
# Recoleccion
# --------------------------------------------------------------------------- #

def consultar_celda(cliente: ClienteGoogle, consulta: str, celda: dict[str, Any],
                    idioma: str, region: str | None, max_paginas: int) -> Iterator[dict[str, Any]]:
    """Ejecuta una busqueda de texto restringida a una celda, con paginacion."""
    cuerpo: dict[str, Any] = {
        "textQuery": consulta,
        "languageCode": idioma,
        "maxResultCount": MAX_RESULTADOS_POR_PAGINA,
        "locationRestriction": {
            "rectangle": {"low": celda["low"], "high": celda["high"]}
        },
    }
    if region:
        cuerpo["regionCode"] = region.upper()

    token: str | None = None
    for _ in range(max_paginas):
        if token:
            cuerpo["pageToken"] = token
        datos = cliente.buscar_texto(cuerpo)
        for lugar in datos.get("places", []) or []:
            yield lugar
        token = datos.get("nextPageToken")
        if not token:
            return


def aplanar_lugar(lugar: dict[str, Any], consulta: str) -> dict[str, Any]:
    """Convierte la respuesta de la API en una fila plana para exportar."""
    componentes = {}
    for componente in lugar.get("addressComponents", []) or []:
        for tipo in componente.get("types", []):
            componentes.setdefault(tipo, componente.get("longText"))

    horarios = lugar.get("regularOpeningHours", {}) or {}
    ubicacion = lugar.get("location", {}) or {}

    return {
        "place_id": lugar.get("id"),
        "nombre": (lugar.get("displayName") or {}).get("text"),
        "categoria_consultada": consulta,
        "tipo_principal": (lugar.get("primaryTypeDisplayName") or {}).get("text")
                          or lugar.get("primaryType"),
        "tipos": ", ".join(lugar.get("types", []) or []),
        "estado_negocio": lugar.get("businessStatus"),
        "direccion": lugar.get("formattedAddress"),
        "direccion_corta": lugar.get("shortFormattedAddress"),
        "municipio": componentes.get("locality") or componentes.get("administrative_area_level_2"),
        "departamento": componentes.get("administrative_area_level_1"),
        "pais": componentes.get("country"),
        "codigo_postal": componentes.get("postal_code"),
        "latitud": ubicacion.get("latitude"),
        "longitud": ubicacion.get("longitude"),
        "plus_code": (lugar.get("plusCode") or {}).get("globalCode"),
        "telefono_nacional": lugar.get("nationalPhoneNumber"),
        "telefono_internacional": lugar.get("internationalPhoneNumber"),
        "sitio_web": lugar.get("websiteUri"),
        "url_google_maps": lugar.get("googleMapsUri"),
        "calificacion": lugar.get("rating"),
        "total_resenas": lugar.get("userRatingCount"),
        "nivel_precio": lugar.get("priceLevel"),
        "abierto_ahora": horarios.get("openNow"),
        "horario": " | ".join(horarios.get("weekdayDescriptions", []) or []),
        "fecha_extraccion": datetime.now().isoformat(timespec="seconds"),
    }


def recolectar(cliente: ClienteGoogle, celdas: list[dict[str, Any]], categorias: list[str],
               idioma: str, region: str | None, filtro_direccion: str,
               max_paginas: int, registros: dict[str, dict[str, Any]]) -> None:
    """Recorre celdas x categorias y acumula los registros deduplicados."""
    total_consultas = len(celdas) * len(categorias)
    hecho = 0
    descartados = 0
    filtro = normalizar(filtro_direccion)

    for celda in celdas:
        for categoria in categorias:
            hecho += 1
            nuevos = 0
            for lugar in consultar_celda(cliente, categoria, celda, idioma, region, max_paginas):
                place_id = lugar.get("id")
                if not place_id or place_id in registros:
                    continue
                fila = aplanar_lugar(lugar, categoria)
                if filtro:
                    referencia = normalizar(
                        f"{fila.get('direccion') or ''} {fila.get('municipio') or ''}"
                    )
                    if filtro not in referencia:
                        descartados += 1
                        continue
                registros[place_id] = fila
                nuevos += 1
            log(
                f"[{hecho}/{total_consultas}] celda {celda['fila']}-{celda['columna']} "
                f"| '{categoria}' | nuevos: {nuevos} | acumulado: {len(registros)}"
            )

    if descartados:
        log(f"Se descartaron {descartados} resultados fuera del filtro de direccion.")


# --------------------------------------------------------------------------- #
# Exportacion
# --------------------------------------------------------------------------- #

def exportar_csv(filas: list[dict[str, Any]], ruta: Path) -> None:
    columnas = list(filas[0].keys())
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)


def exportar_json(filas: list[dict[str, Any]], ruta: Path) -> None:
    ruta.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")


def exportar_geojson(filas: list[dict[str, Any]], ruta: Path) -> None:
    caracteristicas = []
    for fila in filas:
        if fila.get("latitud") is None or fila.get("longitud") is None:
            continue
        caracteristicas.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [fila["longitud"], fila["latitud"]]},
            "properties": {k: v for k, v in fila.items() if k not in ("latitud", "longitud")},
        })
    coleccion = {"type": "FeatureCollection", "features": caracteristicas}
    ruta.write_text(json.dumps(coleccion, ensure_ascii=False, indent=2), encoding="utf-8")


def exportar_xlsx(filas: list[dict[str, Any]], ruta: Path) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        log("Aviso: 'openpyxl' no esta instalado; se omite el XLSX (pip install openpyxl).")
        return False

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Empresas"
    columnas = list(filas[0].keys())
    hoja.append(columnas)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in filas:
        hoja.append([fila.get(col) for col in columnas])
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    for indice, columna in enumerate(columnas, start=1):
        ancho = max(len(columna) + 2,
                    min(50, max((len(str(f.get(columna) or "")) for f in filas), default=10) + 2))
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    libro.save(ruta)
    return True


def exportar(registros: dict[str, dict[str, Any]], directorio: Path, prefijo: str,
             formatos: list[str]) -> list[Path]:
    if not registros:
        log("No hay registros para exportar.")
        return []

    directorio.mkdir(parents=True, exist_ok=True)
    filas = sorted(registros.values(), key=lambda f: (f.get("nombre") or "").casefold())
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    generados: list[Path] = []

    acciones = {
        "csv": (".csv", exportar_csv),
        "json": (".json", exportar_json),
        "geojson": (".geojson", exportar_geojson),
        "xlsx": (".xlsx", exportar_xlsx),
    }
    for formato in formatos:
        if formato not in acciones:
            log(f"Formato desconocido, se omite: {formato}")
            continue
        extension, funcion = acciones[formato]
        ruta = directorio / f"{prefijo}_{marca}{extension}"
        if funcion(filas, ruta) is False:
            continue
        generados.append(ruta)
        log(f"Archivo generado: {ruta}  ({len(filas)} registros)")
    return generados


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga registros de empresas de Google Maps (Places API New).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--api-key", help="API key de Google. Por defecto usa GOOGLE_MAPS_API_KEY.")
    parser.add_argument("--distrito", default="Distrito de San Salvador, San Salvador, El Salvador",
                        help="Area a consultar (se geocodifica para obtener sus limites).")
    parser.add_argument("--bbox", help="Rectangulo manual: sur,oeste,norte,este (omite la geocodificacion).")
    parser.add_argument("--paso", type=float, default=1000.0,
                        help="Lado aproximado de cada celda en metros (menor = mas cobertura y mas costo). Def: 1000.")
    parser.add_argument("--categorias",
                        help="Lista separada por comas. Por defecto usa el catalogo interno de %d categorias."
                             % len(CATEGORIAS_POR_DEFECTO))
    parser.add_argument("--idioma", default="es", help="Codigo de idioma de los resultados. Def: es.")
    parser.add_argument("--region", default="SV", help="Codigo de pais ISO para sesgar resultados. Def: SV.")
    parser.add_argument("--filtro-direccion", default="San Salvador",
                        help="Conserva solo resultados cuya direccion contenga este texto. Use '' para desactivar.")
    parser.add_argument("--max-paginas", type=int, default=MAX_PAGINAS,
                        help="Paginas por consulta (1-3, 20 resultados c/u). Def: 3.")
    parser.add_argument("--pausa", type=float, default=0.2,
                        help="Segundos de espera entre peticiones. Def: 0.2.")
    parser.add_argument("--salida", default="datos", help="Carpeta de salida. Def: datos.")
    parser.add_argument("--prefijo", default="empresas_san_salvador", help="Prefijo de los archivos generados.")
    parser.add_argument("--formatos", default="csv,xlsx,json",
                        help="Formatos separados por comas: csv, xlsx, json, geojson. Def: csv,xlsx,json.")
    parser.add_argument("--limite-celdas", type=int,
                        help="Procesa solo las primeras N celdas (util para pruebas).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo muestra la grilla, el numero de peticiones y el costo estimado.")
    parser.add_argument("--si", "--yes", dest="si", action="store_true",
                        help="No pedir confirmacion aunque la busqueda sea grande (uso desatendido).")
    parser.add_argument("--umbral-confirmacion", type=int, default=500,
                        help="Pide confirmacion si se superan estas peticiones estimadas. Def: 500.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    categorias = [c.strip() for c in args.categorias.split(",") if c.strip()] if args.categorias \
        else list(CATEGORIAS_POR_DEFECTO)
    formatos = [f.strip().lower() for f in args.formatos.split(",") if f.strip()]
    max_paginas = max(1, min(args.max_paginas, MAX_PAGINAS))

    api_key = obtener_api_key(args.api_key)
    cliente = ClienteGoogle(api_key, pausa=args.pausa)

    bbox = resolver_bbox(cliente, args.distrito, args.region, args.bbox)
    log(f"Area: sur={bbox['sur']:.5f} oeste={bbox['oeste']:.5f} "
        f"norte={bbox['norte']:.5f} este={bbox['este']:.5f}")

    celdas = generar_celdas(bbox, args.paso)
    if args.limite_celdas:
        celdas = celdas[:args.limite_celdas]

    consultas = len(celdas) * len(categorias)
    peticiones_max = consultas * max_paginas
    log(f"Grilla: {len(celdas)} celdas de ~{args.paso:.0f} m x {len(categorias)} categorias "
        f"= {consultas} consultas (hasta {peticiones_max} peticiones).")
    log(f"Costo estimado maximo: ~USD {peticiones_max * COSTO_ESTIMADO_POR_1000 / 1000:.2f} "
        f"(tarifa referencial; verifique la de su cuenta). El gasto real suele ser bastante "
        f"menor: solo se pide la pagina 2 y 3 cuando la consulta devuelve mas resultados.")

    if args.dry_run:
        log("Modo --dry-run: no se ejecutaron consultas.")
        return 0

    if peticiones_max > args.umbral_confirmacion and not args.si:
        if not sys.stdin.isatty():
            log("Busqueda grande y sin terminal interactiva: use --si para confirmar, "
                "o reduzca --categorias / --limite-celdas / suba --paso.")
            return 1
        respuesta = input(f"Se ejecutaran hasta {peticiones_max} peticiones facturables. "
                          f"Continuar? [s/N]: ").strip().lower()
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            log("Cancelado por el usuario.")
            return 1

    registros: dict[str, dict[str, Any]] = {}
    inicio = time.time()
    try:
        recolectar(cliente, celdas, categorias, args.idioma, args.region,
                   args.filtro_direccion, max_paginas, registros)
    except KeyboardInterrupt:
        log("Interrumpido por el usuario; se exporta lo recolectado hasta ahora.")

    duracion = time.time() - inicio
    log(f"Peticiones realizadas: {cliente.peticiones} | "
        f"empresas unicas: {len(registros)} | tiempo: {duracion/60:.1f} min")

    exportar(registros, Path(args.salida), args.prefijo, formatos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
