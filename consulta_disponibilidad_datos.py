#!/usr/bin/env python3
"""
Catalogo de disponibilidad de datos geoespaciales / empresariales para El Salvador.

Recorre, por etapa, las fuentes identificadas en la investigacion (HDX, Geoportal BCR,
CNR, Geofabrik, catastro/uso de suelo, Overture Places, Foursquare OS Places, VIDA
buildings, GEOEDUCACION, MINSAL, SSF, OSM/Overpass) y reporta que hay disponible y en
que formato, SIN descargar datasets completos: usa HEAD requests, metadatos de API
(CKAN/ArcGIS REST/WMS) y consultas DuckDB acotadas por bbox contra los Parquet en la
nube (Overture, Foursquare, VIDA).

Uso:
    pip install -r requirements.txt
    python consulta_disponibilidad_datos.py --etapas all --out-json reporte.json --out-csv reporte.csv

    # Solo una etapa:
    python consulta_disponibilidad_datos.py --etapas 3

    # Generar tambien las cartas LAIP:
    python consulta_disponibilidad_datos.py --etapas laip --laip-solicitante "Nombre Apellido" --laip-correo correo@ejemplo.com
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuracion general
# ---------------------------------------------------------------------------

# bbox de El Salvador: (oeste, sur, este, norte) en grados decimales (WGS84)
BBOX_EL_SALVADOR = (-90.15, 13.15, -87.65, 14.45)
AREA_EL_SALVADOR_KM2 = 21041.0  # superficie territorial aproximada

TIMEOUT = 20
HEADERS = {"User-Agent": "consulta-disponibilidad-datos-es/1.0 (uso academico/GIS)"}

ESTADOS = ("disponible", "parcial", "no_disponible", "error", "requiere_verificacion", "requiere_laip")


@dataclass
class Hallazgo:
    etapa: str
    fuente: str
    tipo: str
    formato: str
    estado: str
    url: str
    detalle: str = ""
    notas: str = ""


RESULTADOS: list[Hallazgo] = []


def registrar(h: Hallazgo) -> Hallazgo:
    RESULTADOS.append(h)
    marca = {
        "disponible": "[OK]",
        "parcial": "[~ ]",
        "no_disponible": "[NO]",
        "error": "[ERR]",
        "requiere_verificacion": "[? ]",
        "requiere_laip": "[LAIP]",
    }.get(h.estado, "[??]")
    print(f"{marca} {h.etapa} | {h.fuente} -> {h.detalle}")
    return h


# ---------------------------------------------------------------------------
# Utilidades HTTP genericas
# ---------------------------------------------------------------------------

def head_o_get(url: str, timeout: int = TIMEOUT) -> dict:
    """Intenta HEAD; si el servidor no lo soporta bien, reintenta con GET truncado."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400 or "Content-Length" not in r.headers:
            r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            r.close()
        return {
            "ok": r.status_code < 400,
            "status_code": r.status_code,
            "content_length": r.headers.get("Content-Length"),
            "last_modified": r.headers.get("Last-Modified"),
            "content_type": r.headers.get("Content-Type"),
            "url_final": r.url,
        }
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}


def check_url_generico(etapa: str, fuente: str, tipo: str, formato: str, url: str, nota: str = "") -> Hallazgo:
    info = head_o_get(url)
    if info.get("ok"):
        tam = info.get("content_length")
        tam_txt = f", {int(tam) / 1_048_576:.1f} MB" if tam and tam.isdigit() else ""
        detalle = f"accesible (HTTP {info['status_code']}{tam_txt})"
        estado = "disponible"
    elif "error" in info:
        detalle = f"error de conexion: {info['error']}"
        estado = "error"
    else:
        detalle = f"HTTP {info.get('status_code')}"
        estado = "no_disponible"
    return registrar(Hallazgo(etapa, fuente, tipo, formato, estado, url, detalle, nota))


def check_ckan_dataset(etapa: str, fuente: str, base_api: str, dataset_id: str, nota: str = "") -> None:
    url = f"{base_api}/api/3/action/package_show?id={dataset_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            registrar(Hallazgo(etapa, fuente, "metadato CKAN", "json", "no_disponible", url,
                                "package_show no exitoso", nota))
            return
        recursos = data["result"].get("resources", [])
        if not recursos:
            registrar(Hallazgo(etapa, fuente, "metadato CKAN", "json", "parcial", url,
                                "dataset existe pero sin recursos listados", nota))
            return
        for rec in recursos:
            registrar(Hallazgo(
                etapa, f"{fuente} :: {rec.get('name', 'sin nombre')}",
                "descarga directa", rec.get("format", "?"),
                "disponible", rec.get("url", url),
                f"tamano={rec.get('size')} bytes, actualizado={rec.get('last_modified') or rec.get('created')}",
                nota,
            ))
    except requests.RequestException as e:
        registrar(Hallazgo(etapa, fuente, "metadato CKAN", "json", "error", url, str(e), nota))


def check_arcgis_featureserver(etapa: str, fuente: str, base_url: str, nota: str = "") -> None:
    """Consulta ArcGIS REST (FeatureServer/MapServer): capas y conteo de features por capa."""
    info_url = f"{base_url.rstrip('/')}?f=json"
    try:
        r = requests.get(info_url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        meta = r.json()
        if "error" in meta:
            registrar(Hallazgo(etapa, fuente, "ArcGIS REST", "json", "no_disponible", base_url,
                                f"error del servicio: {meta['error']}", nota))
            return
        capas = meta.get("layers", []) or ([meta] if "type" in meta and "fields" in meta else [])
        if not capas:
            registrar(Hallazgo(etapa, fuente, "ArcGIS REST", "json", "parcial", base_url,
                                "servicio responde pero sin capas listadas", nota))
            return
        for capa in capas:
            lid = capa.get("id", 0)
            nombre = capa.get("name", f"capa_{lid}")
            count_url = f"{base_url.rstrip('/')}/{lid}/query?where=1%3D1&returnCountOnly=true&f=json"
            n = "?"
            try:
                rc = requests.get(count_url, headers=HEADERS, timeout=TIMEOUT)
                n = rc.json().get("count", "?")
            except requests.RequestException:
                pass
            registrar(Hallazgo(
                etapa, f"{fuente} :: {nombre}", "capa ArcGIS", "FeatureServer/JSON, GeoJSON, Shapefile (export)",
                "disponible", f"{base_url.rstrip('/')}/{lid}",
                f"{n} registros", nota,
            ))
    except requests.RequestException as e:
        registrar(Hallazgo(etapa, fuente, "ArcGIS REST", "json", "error", base_url, str(e), nota))


def check_wms_capabilities(etapa: str, fuente: str, url: str, nota: str = "") -> None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        nombres = [el.text for el in root.iter() if el.tag.endswith("}Name") or el.tag == "Name"]
        # el primer "Name" suele ser el del servicio; las capas vienen despues
        capas = nombres[1:] if len(nombres) > 1 else nombres
        registrar(Hallazgo(
            etapa, fuente, "WMS GetCapabilities", "WMS (GetMap/GetFeatureInfo)",
            "disponible" if capas else "parcial", url,
            f"{len(capas)} capas: {', '.join(capas[:15])}{' ...' if len(capas) > 15 else ''}",
            nota,
        ))
    except (requests.RequestException, ET.ParseError) as e:
        registrar(Hallazgo(etapa, fuente, "WMS GetCapabilities", "WMS", "error", url, str(e), nota))


# ---------------------------------------------------------------------------
# ETAPA 1 - Base cartografica y limites
# ---------------------------------------------------------------------------

def etapa1_base_cartografica() -> None:
    E = "Etapa 1 - Cartografia y limites"

    # HDX COD-AB El Salvador (limites admin ADM0-ADM3: departamento/municipio/distrito)
    check_ckan_dataset(E, "HDX COD-AB El Salvador (cod-ab-slv)", "https://data.humdata.org", "cod-ab-slv",
                        nota="Tras la reforma territorial 2024: 14 departamentos / 44 municipios / 262 distritos. "
                             "Verificar que el recurso descargado ya refleje la division vigente (ADM2=municipio, "
                             "ADM3=distrito) y no la anterior (262 municipios).")

    # Geoportal BCR (censo 2024 / limites) - sin API publica confirmada, se verifica accesibilidad del portal
    check_url_generico(E, "Geoportal BCR - Censo 2024 (portada)", "portal", "html",
                        "https://censo2024.bcr.gob.sv/", nota="Portal navegable; descargas de tablas y mapas "
                        "parecen requerir navegacion manual por seccion/departamento (no se confirmo API REST).")
    check_url_generico(E, "Geoportal BCR - Poblacion (tabulados)", "portal", "html",
                        "https://poblacion.bcr.gob.sv/pages/teg-base-de-datos-y-tabulados",
                        nota="Revisar manualmente si expone shapefile/GeoJSON de limites o solo tabulados PDF/XLSX.")

    # CNR - Centro Nacional de Registros (base topografica: vial, hidrografia, relieve)
    check_url_generico(E, "CNR - Geoportal / Instituto Geografico Nacional", "portal", "html/varios",
                        "https://www.cnr.gob.sv/", nota="Base topografica oficial (vial, hidrografia, curvas de "
                        "nivel). Historicamente requiere solicitud/convenio o el visor del IGN-CNR; verificar "
                        "geoportal especifico y si permite descarga directa de capas vectoriales.")

    # Geofabrik (topografia OSM: vial, hidrografia, uso de suelo basico) - descarga directa verificable
    base = "https://download.geofabrik.de/central-america/el-salvador"
    for nombre, sufijo, formato in [
        ("OSM PBF (todo el pais)", "-latest.osm.pbf", "osm.pbf"),
        ("Shapefile (todas las capas)", "-latest-free.shp.zip", "shp.zip"),
        ("GeoPackage (todas las capas)", "-latest-free.gpkg.zip", "gpkg.zip"),
    ]:
        check_url_generico(E, f"Geofabrik :: {nombre}", "descarga directa", formato, f"{base}{sufijo}",
                            nota="Incluye red vial, hidrografia y relieve derivados de OSM; actualizacion diaria.")


# ---------------------------------------------------------------------------
# ETAPA 2 - Demografia y uso de suelo
# ---------------------------------------------------------------------------

def worldcover_tile_name(lat0: int, lon0: int) -> str:
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def worldcover_tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[str]:
    w, s, e, n = bbox
    tiles = []
    lat0 = math.floor(s / 3) * 3
    while lat0 < n:
        lon0 = math.floor(w / 3) * 3
        while lon0 < e:
            tiles.append(worldcover_tile_name(lat0, lon0))
            lon0 += 3
        lat0 += 3
    return tiles


def etapa2_demografia_uso_suelo(bbox) -> None:
    E = "Etapa 2 - Demografia y uso de suelo"

    # Censo 2024 (BCR) - tabulados por departamento/municipio/distrito
    check_url_generico(E, "BCR Censo 2024 - tabla de ejemplo (mortalidad)", "tabulado", "pdf",
                        "https://censo2024.bcr.gob.sv/wp-content/uploads/tablas-geoportal/2025/TAB_MORT_1.pdf",
                        nota="Los tabulados publicados en este directorio estan en PDF, no CSV. Antes de asumir "
                        "CSV, revisar el listado completo de 'tablas-geoportal' por anio/mes; si no hay CSV, "
                        "extraer con pdfplumber/camelot o solicitar microdato via LAIP a ONEC/BCR.")

    # IGCN - catastro nacional
    check_url_generico(E, "IGCN - Instituto Geografico y del Catastro Nacional", "portal", "html/varios",
                        "https://www.catastro.gob.sv/", nota="Catastro nacional; capa de uso de suelo/parcelas "
                        "normalmente restringida. Verificar visor publico vs. acceso por convenio/LAIP.")

    # OPAMSS - uso de suelo AMSS (geoportal propio, posible WFS/GeoServer)
    check_url_generico(E, "OPAMSS - Geoportal (Sistema de Informacion Metropolitano)", "portal", "html",
                        "https://geoportal.opamss.org.sv/portal/", nota="Buscar capa 'Uso de suelo' dentro del "
                        "geovisor; probar tambien geoservicios WFS/WMS si el backend es GeoServer.")
    check_url_generico(E, "OPAMSS - intento WFS GetCapabilities", "WFS", "xml",
                        "https://geoportal.opamss.org.sv/geoserver/wfs?service=WFS&version=2.0.0&request=GetCapabilities",
                        nota="Ruta candidata generica; si falla, el geovisor puede usar otro backend (ArcGIS/MapServer).")

    # ESA WorldCover 10 m - AWS Open Data (publico, sin credenciales)
    for year, version in [("2021", "v200"), ("2020", "v100")]:
        for tile in worldcover_tiles_for_bbox(bbox):
            url = (f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/{version}/{year}/map/"
                   f"ESA_WorldCover_10m_{year}_{version}_{tile}_Map.tif")
            check_url_generico(E, f"ESA WorldCover {year} ({version}) :: tile {tile}", "raster 10m", "COG/GeoTIFF",
                                url, nota="Cobertura de suelo global 10 m; bucket S3 publico, sin necesidad de token.")

    # MAG - Mapa Digital de Suelos
    check_url_generico(E, "MAG - Mapa Digital de Suelos", "portal", "html/varios",
                        "https://www.mag.gob.sv/", nota="Verificar seccion de Direccion General de Ordenamiento "
                        "Forestal, Cuencas y Riego o CENTA; el mapa de suelos suele distribuirse como shapefile "
                        "bajo solicitud, no siempre con descarga directa publica.")


# ---------------------------------------------------------------------------
# ETAPA 3 - POI/empresas y edificaciones (DuckDB sobre Parquet en la nube)
# ---------------------------------------------------------------------------

def _duckdb_conn():
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL spatial; LOAD spatial;")
    # path-style es necesario porque el bucket de source.coop (VIDA) tiene puntos en el
    # nombre ('us-west-2.opendata.source.coop'), lo que rompe el direccionamiento
    # virtual-hosted-style por certificado TLS.
    con.execute("SET s3_url_style='path';")
    return con


def discover_latest_s3_prefix(bucket: str, prefix: str, region: str = "us-west-2") -> Optional[str]:
    """Lista 'directorios' (CommonPrefixes) publicos de un bucket S3 via la API REST, sin credenciales."""
    host = f"https://{bucket}.s3.{region}.amazonaws.com" if region != "us-east-1" else f"https://{bucket}.s3.amazonaws.com"
    url = f"{host}/?list-type=2&delimiter=/&prefix={prefix}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    root = ET.fromstring(r.content)
    prefijos = [cp.findtext("s3:Prefix", namespaces=ns) for cp in root.findall("s3:CommonPrefixes", ns)]
    subcarpetas = sorted(p.split("/")[-2] for p in prefijos if p)
    return subcarpetas[-1] if subcarpetas else None


def etapa3_poi_edificaciones(bbox, umbral_densidad: float, overture_release: Optional[str],
                              fsq_release_date: Optional[str]) -> None:
    E = "Etapa 3 - POI/empresas y edificaciones"
    w, s, e, n = bbox

    try:
        con = _duckdb_conn()
    except ImportError:
        registrar(Hallazgo(E, "DuckDB", "dependencia", "-", "error", "-",
                            "duckdb no instalado. Ejecuta: pip install duckdb"))
        return
    except Exception as ex:
        registrar(Hallazgo(E, "DuckDB", "extensiones httpfs/spatial", "-", "error", "-", str(ex),
                            "Revisa conectividad para descargar las extensiones httpfs/spatial la primera vez."))
        return

    # --- Overture Maps Places ---
    overture_total = None
    try:
        con.execute("SET s3_region='us-west-2';")
        release = overture_release or discover_latest_s3_prefix("overturemaps-us-west-2", "release/")
        path = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
        sql_total = f"""
            SELECT count(*) FROM read_parquet('{path}', hive_partitioning=1)
            WHERE bbox.xmin <= {e} AND bbox.xmax >= {w} AND bbox.ymin <= {n} AND bbox.ymax >= {s}
        """
        overture_total = con.execute(sql_total).fetchone()[0]
        sql_top = f"""
            SELECT categories.primary AS categoria, count(*) AS n
            FROM read_parquet('{path}', hive_partitioning=1)
            WHERE bbox.xmin <= {e} AND bbox.xmax >= {w} AND bbox.ymin <= {n} AND bbox.ymax >= {s}
            GROUP BY 1 ORDER BY n DESC LIMIT 15
        """
        top = con.execute(sql_top).fetchall()
        densidad = overture_total / AREA_EL_SALVADOR_KM2
        registrar(Hallazgo(
            E, f"Overture Maps Places (release {release})", "POI (consulta bbox, sin descarga completa)",
            "GeoParquet en S3 (read_parquet vía DuckDB)", "disponible", path,
            f"{overture_total} lugares en bbox de El Salvador (~{densidad:.2f} POI/km2). "
            f"Top categorias: {', '.join(f'{c}={n}' for c, n in top[:8])}",
        ))
    except Exception as ex:
        registrar(Hallazgo(E, "Overture Maps Places", "POI", "GeoParquet/S3", "error", "-", str(ex)))

    # --- Foursquare Open Source Places ---
    fsq_total = None
    try:
        con.execute("SET s3_region='us-east-1';")
        date = fsq_release_date or discover_latest_s3_prefix("fsq-os-places-us-east-1", "release/", region="us-east-1")
        path = f"s3://fsq-os-places-us-east-1/release/{date}/places/parquet/*.parquet"
        sql = f"""
            SELECT count(*) FROM read_parquet('{path}')
            WHERE longitude BETWEEN {w} AND {e} AND latitude BETWEEN {s} AND {n}
        """
        fsq_total = con.execute(sql).fetchone()[0]
        densidad = fsq_total / AREA_EL_SALVADOR_KM2
        registrar(Hallazgo(
            E, f"Foursquare OS Places (release {date})", "POI (consulta bbox, sin descarga completa)",
            "Parquet en S3 (read_parquet vía DuckDB)", "disponible", path,
            f"{fsq_total} lugares en bbox de El Salvador (~{densidad:.2f} POI/km2).",
            nota="Desde oct-2025 Foursquare movio las publicaciones nuevas a un portal con token + catalogo "
                 "Iceberg; el bucket S3 publico puede seguir sirviendo solo releases anteriores. Si esta consulta "
                 "falla, registrarse en el portal de FSQ Places y usar el token/Iceberg en vez del S3 directo.",
        ))
    except Exception as ex:
        registrar(Hallazgo(E, "Foursquare OS Places", "POI", "Parquet/S3", "error", "-", str(ex),
                            "Puede requerir el nuevo portal de Foursquare (token de acceso) si el bucket publico "
                            "ya no sirve releases recientes."))

    # --- Comparacion de densidad y recomendacion segun umbral ---
    if overture_total is not None or fsq_total is not None:
        valores = [v for v in (overture_total, fsq_total) if v is not None]
        densidad_max = max(v / AREA_EL_SALVADOR_KM2 for v in valores)
        if densidad_max < umbral_densidad:
            registrar(Hallazgo(
                E, "Umbral de densidad POI", "decision", "-", "requiere_verificacion", "-",
                f"Densidad maxima observada ({densidad_max:.2f} POI/km2) por DEBAJO del umbral "
                f"configurado ({umbral_densidad} POI/km2).",
                notas="RECOMENDACION: priorizar OSM/Geofabrik + geocodificacion de directorios gremiales "
                      "en vez de depender de Overture/Foursquare para POI/empresas. Ajustar --umbral-densidad "
                      "si se dispone de un umbral oficial distinto.",
            ))
        else:
            registrar(Hallazgo(
                E, "Umbral de densidad POI", "decision", "-", "disponible", "-",
                f"Densidad maxima observada ({densidad_max:.2f} POI/km2) por ENCIMA del umbral "
                f"({umbral_densidad} POI/km2): Overture/Foursquare son viables como fuente principal de POI.",
            ))

    # --- VIDA combined buildings (Google+Microsoft+OSM), particionado por country_iso ---
    try:
        con.execute("SET s3_region='us-west-2';")
        prefix = "s3://us-west-2.opendata.source.coop/vida/google-microsoft-osm-open-buildings/geoparquet"
        path = f"{prefix}/by_country_s2/country_iso=SLV/*.parquet"
        total = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        detalle = f"{total} huellas de edificacion para El Salvador (country_iso=SLV)."
        try:
            por_fuente = con.execute(
                f"SELECT source, count(*) FROM read_parquet('{path}') GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
            detalle += " Por fuente: " + ", ".join(f"{f}={n}" for f, n in por_fuente)
        except Exception:
            pass  # el nombre de columna de fuente puede variar entre versiones del dataset
        registrar(Hallazgo(
            E, "VIDA combined buildings (Google+Microsoft+OSM)",
            "huellas de edificacion (consulta pais, sin descarga completa)",
            "GeoParquet en S3 (read_parquet vía DuckDB)", "disponible", path, detalle,
        ))
    except Exception as ex:
        # fallback: dataset anterior de solo Google+Microsoft, particionado por pais (un solo archivo)
        try:
            path_legacy = ("s3://us-west-2.opendata.source.coop/vida/google-microsoft-open-buildings/"
                           "geoparquet/by_country/country_iso=SLV/SLV.parquet")
            total = con.execute(f"SELECT count(*) FROM read_parquet('{path_legacy}')").fetchone()[0]
            registrar(Hallazgo(
                E, "VIDA combined buildings (fallback Google+Microsoft, sin OSM)",
                "huellas de edificacion", "GeoParquet en S3", "disponible", path_legacy,
                f"{total} huellas de edificacion para El Salvador (dataset legado, sin capa OSM).",
            ))
        except Exception as ex2:
            registrar(Hallazgo(E, "VIDA combined buildings", "huellas de edificacion", "GeoParquet/S3", "error",
                                "-", f"{ex} / fallback: {ex2}"))

    # Geofabrik como complemento de POI/edificaciones ya se descarga en Etapa 1 (osm.pbf / shp.zip / gpkg.zip)
    registrar(Hallazgo(
        E, "Geofabrik (complemento OSM)", "POI + edificaciones", "osm.pbf/shp.zip/gpkg.zip", "disponible", "-",
        "Reutilizar los archivos verificados en la Etapa 1; para contar POI/edificios localmente usar "
        "osmium/pyrosm sobre el .osm.pbf (no requiere red).",
    ))


# ---------------------------------------------------------------------------
# ETAPA 4 - Equipamientos e infraestructura
# ---------------------------------------------------------------------------

def overpass_conteo(bbox, categorias: dict[str, str]) -> dict[str, int | str]:
    """categorias: {etiqueta: filtro_overpass_ql}, p.ej. {'escuelas': 'amenity=school'}"""
    w, s, e, n = bbox
    partes = []
    for i, filtro in enumerate(categorias.values()):
        partes.append(f'node[{filtro}]({s},{w},{n},{e});')
        partes.append(f'way[{filtro}]({s},{w},{n},{e});')
    consulta = "[out:json][timeout:60];(" + "".join(partes) + ");out count;"
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": consulta}, timeout=90)
    r.raise_for_status()
    return r.json()


def etapa4_equipamientos(bbox) -> None:
    E = "Etapa 4 - Equipamientos e infraestructura"

    # GEOEDUCACION - MINEDUCYT (ArcGIS REST, capa Centros Educativos confirmada)
    check_arcgis_featureserver(
        E, "GEOEDUCACION - Centros Educativos (MINEDUCYT)",
        "https://services3.arcgis.com/PYyU96woLS4j2PN8/arcgis/rest/services/CentrosEducativos/FeatureServer",
        nota="Portal publico: https://geo.educacion.goes.gob.sv/ . Exportable a GeoJSON/Shapefile via ArcGIS REST.")

    # MINSAL - geo.salud (WMS)
    check_wms_capabilities(
        E, "MINSAL - Establecimientos de salud (WMS)",
        "http://geo.salud.gob.sv/cgi-bin/mapserv?MAP=/var/www/geo/geo/maps/wms/minsal.map"
        "&SERVICE=WMS&REQUEST=GetCapabilities",
        nota="WMS solo entrega imagenes/GetFeatureInfo; para vector conviene pedir el shapefile directamente "
             "a MINSAL o extraer via GetFeatureInfo punto a punto.")

    # SSF - bancos (sin API/geolocalizacion nativa; requiere geocodificar el directorio)
    check_url_generico(E, "SSF - Superintendencia del Sistema Financiero (directorio de bancos)", "portal",
                        "html", "https://www.ssf.gob.sv/", nota="No se identifico API ni capa geoespacial. "
                        "Extraer el listado de agencias/sucursales del sitio o de sus informes y geocodificar "
                        "direcciones (Nominatim/Google Geocoding) para obtener coordenadas.")

    # OSM/Overpass como fuente complementaria/de respaldo para equipamientos
    categorias = {
        "escuelas": 'amenity=school',
        "hospitales_clinicas": 'amenity~"hospital|clinic|doctors"',
        "bancos": 'amenity=bank',
        "cajeros": 'amenity=atm',
        "farmacias": 'amenity=pharmacy',
    }
    try:
        data = overpass_conteo(bbox, categorias)
        total = sum(int(el.get("tags", {}).get("total", 0)) for el in data.get("elements", []))
        registrar(Hallazgo(
            E, "OSM / Overpass (equipamientos, respaldo)", "equipamientos", "JSON/Overpass QL", "disponible",
            "https://overpass-api.de/api/interpreter",
            f"{total} elementos combinados para {list(categorias.keys())} dentro del bbox de El Salvador.",
            nota="Util como cobertura de respaldo/complemento donde GEOEDUCACION, MINSAL o SSF no alcancen; "
                 "consultar por categoria individual para desglosar el conteo.",
        ))
    except Exception as ex:
        registrar(Hallazgo(E, "OSM / Overpass (equipamientos, respaldo)", "equipamientos", "JSON/Overpass QL",
                            "error", "https://overpass-api.de/api/interpreter", str(ex)))


# ---------------------------------------------------------------------------
# LAIP - Datos que requieren solicitud formal
# ---------------------------------------------------------------------------

SOLICITUDES_LAIP = [
    {
        "institucion": "ONEC / Banco Central de Reserva (BCR)",
        "dato": "Directorio de empresas con CIIU y tamano, georreferenciado",
        "base_legal": "Ley de Acceso a la Informacion Publica (LAIP), Art. 62 y ss. (informacion no clasificada "
                       "como reservada ni confidencial)",
    },
    {
        "institucion": "Ministerio de Medio Ambiente y Recursos Naturales (MARN)",
        "dato": "Informacion geoambiental tarifada (capas ambientales de detalle)",
        "base_legal": "LAIP; verificar tarifa vigente segun el Reglamento de la Ley y la Unidad de Acceso a la "
                       "Informacion Publica (UAIP) del MARN",
    },
    {
        "institucion": "ONEC / BCR, CNR o MARN",
        "dato": "Microdatos censales de establecimientos (censo economico/poblacion 2024, nivel establecimiento)",
        "base_legal": "LAIP; los microdatos de unidad economica suelen requerir anonimizacion o convenio de uso",
    },
]


MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre"]


def plantilla_laip(institucion: str, dato: str, base_legal: str, solicitante: str, correo: str) -> str:
    ahora = datetime.now(timezone.utc).astimezone()
    hoy = f"{ahora.day} de {MESES_ES[ahora.month - 1]} de {ahora.year}"
    return f"""SOLICITUD DE ACCESO A LA INFORMACION PUBLICA (LAIP)

Fecha: {hoy}
Dirigida a: Unidad de Acceso a la Informacion Publica (UAIP) - {institucion}

Nombre del solicitante: {solicitante}
Correo electronico para notificaciones: {correo}

Informacion solicitada:
{dato}

Fundamento legal: {base_legal}

Formato de entrega solicitado: digital, en formato abierto (CSV, GeoJSON o Shapefile segun corresponda),
preferentemente georreferenciado (WGS84 / EPSG:4326).

Se solicita respuesta dentro del plazo establecido por la Ley de Acceso a la Informacion Publica.

Firma: ____________________________
{solicitante}
"""


def etapa_laip(solicitante: str, correo: str, out_dir: str) -> None:
    E = "LAIP - Solicitud formal"
    import os
    os.makedirs(out_dir, exist_ok=True)
    for item in SOLICITUDES_LAIP:
        texto = plantilla_laip(item["institucion"], item["dato"], item["base_legal"], solicitante, correo)
        nombre_archivo = "laip_" + item["institucion"].lower().replace(" ", "_").replace("/", "-") + ".txt"
        ruta = f"{out_dir.rstrip('/')}/{nombre_archivo}"
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        registrar(Hallazgo(
            E, item["institucion"], "solicitud formal", "carta LAIP (txt)", "requiere_laip", ruta,
            f"Dato solicitado: {item['dato']}",
            notas="Plantilla generada localmente; revisar y presentar por la via oficial de cada UAIP "
                  "(en linea, correo o presencial) segun la institucion.",
        ))


# ---------------------------------------------------------------------------
# Reporte final
# ---------------------------------------------------------------------------

def guardar_reporte(ruta_json: Optional[str], ruta_csv: Optional[str]) -> None:
    if ruta_json:
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump([asdict(h) for h in RESULTADOS], f, ensure_ascii=False, indent=2)
        print(f"\nReporte JSON guardado en: {ruta_json}")
    if ruta_csv:
        with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
            campos = ["etapa", "fuente", "tipo", "formato", "estado", "url", "detalle", "notas"]
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            for h in RESULTADOS:
                w.writerow(asdict(h))
        print(f"Reporte CSV guardado en: {ruta_csv}")


def resumen_consola() -> None:
    print("\n" + "=" * 78)
    print("RESUMEN POR ESTADO")
    print("=" * 78)
    conteo: dict[str, int] = {}
    for h in RESULTADOS:
        conteo[h.estado] = conteo.get(h.estado, 0) + 1
    for estado in ESTADOS:
        if estado in conteo:
            print(f"  {estado:22s}: {conteo[estado]}")
    print(f"  {'TOTAL':22s}: {len(RESULTADOS)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapas", default="all",
                    help="Lista separada por comas: 1,2,3,4,laip  (o 'all')")
    ap.add_argument("--bbox", default=None,
                    help="oeste,sur,este,norte (default: bbox de El Salvador)")
    ap.add_argument("--umbral-densidad", type=float, default=5.0,
                    help="POI/km2 minimo para considerar Overture/Foursquare viables (default: 5.0, ajustar "
                         "si se cuenta con un umbral oficial del proyecto)")
    ap.add_argument("--overture-release", default=None, help="Forzar version de release de Overture (ej. 2025-08-20.0)")
    ap.add_argument("--fsq-release-date", default=None, help="Forzar fecha de release de Foursquare (ej. 2024-11-19)")
    ap.add_argument("--laip-solicitante", default="[NOMBRE DEL SOLICITANTE]")
    ap.add_argument("--laip-correo", default="[correo@ejemplo.com]")
    ap.add_argument("--laip-out-dir", default="./laip")
    ap.add_argument("--out-json", default="reporte_disponibilidad.json")
    ap.add_argument("--out-csv", default="reporte_disponibilidad.csv")
    args = ap.parse_args()

    bbox = BBOX_EL_SALVADOR
    if args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))  # type: ignore[assignment]

    etapas = {e.strip().lower() for e in args.etapas.split(",")}
    todas = etapas == {"all"}

    if todas or "1" in etapas:
        etapa1_base_cartografica()
    if todas or "2" in etapas:
        etapa2_demografia_uso_suelo(bbox)
    if todas or "3" in etapas:
        etapa3_poi_edificaciones(bbox, args.umbral_densidad, args.overture_release, args.fsq_release_date)
    if todas or "4" in etapas:
        etapa4_equipamientos(bbox)
    if todas or "laip" in etapas:
        etapa_laip(args.laip_solicitante, args.laip_correo, args.laip_out_dir)

    resumen_consola()
    guardar_reporte(args.out_json, args.out_csv)


if __name__ == "__main__":
    main()
