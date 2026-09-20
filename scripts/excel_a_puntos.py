#!/usr/bin/env python3
"""Convierte la base unificada de OSM (Excel) en una capa vectorial de puntos.

Uso:
    python scripts/excel_a_puntos.py [ruta_excel] [-o carpeta_salida] [--hoja NOMBRE]

Genera en la carpeta de salida:
    empresas_san_salvador.gpkg      GeoPackage (formato recomendado)
    empresas_san_salvador.geojson   GeoJSON WGS84
    shapefile/empresas_san_salvador.shp
    filas_descartadas.csv           solo si hubo filas sin coordenada valida

El CRS de salida es EPSG:4326 (WGS84 lat/lon), que es el que usa OSM.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

CRS_SALIDA = "EPSG:4326"
NOMBRE_CAPA = "empresas_san_salvador"

# San Salvador. Sirve de control de cordura: avisa si una fila cae fuera del pais.
BBOX_EL_SALVADOR = (-90.2, 13.0, -87.6, 14.5)  # lon_min, lat_min, lon_max, lat_max

# Shapefile trunca los nombres de campo a 10 caracteres. Los acortamos nosotros
# para controlar el resultado en vez de dejar que GDAL invente los nombres.
CAMPOS_SHP = {
    "subcategorias": "subcateg",
    "categoria_principal": "cat_princ",
    "n_categorias": "n_categ",
}


def cargar(ruta: Path, hoja: str | int) -> pd.DataFrame:
    df = pd.read_excel(ruta, sheet_name=hoja)
    faltantes = {"latitud", "longitud"} - set(df.columns)
    if faltantes:
        sys.exit(f"ERROR: al Excel le faltan las columnas {sorted(faltantes)}")
    return df


def limpiar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa las filas con coordenada utilizable de las descartadas."""
    df = df.copy()

    # Tolera coma decimal y espacios si el Excel viene con locale es-*.
    for col in ("latitud", "longitud"):
        if df[col].dtype == object:
            df[col] = (
                df[col].astype(str).str.strip().str.replace(",", ".", regex=False)
            )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    motivo = pd.Series("", index=df.index)
    motivo[df.latitud.isna() | df.longitud.isna()] = "coordenada vacia o no numerica"
    fuera_rango = (df.latitud.abs() > 90) | (df.longitud.abs() > 180)
    motivo[(motivo == "") & fuera_rango] = "coordenada fuera de rango"
    cero = (df.latitud == 0) & (df.longitud == 0)
    motivo[(motivo == "") & cero] = "punto nulo (0, 0)"

    descartadas = df[motivo != ""].assign(motivo_descarte=motivo[motivo != ""])
    return df[motivo == ""].copy(), descartadas


def enriquecer(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega la primera categoria como campo simple, util para simbolizar en QGIS."""
    if "categorias" in df.columns:
        df["categoria_principal"] = (
            df["categorias"].astype(str).str.split("|").str[0].str.strip()
        )
    return df


def avisar_fuera_de_bbox(gdf: gpd.GeoDataFrame) -> None:
    lon_min, lat_min, lon_max, lat_max = BBOX_EL_SALVADOR
    fuera = gdf[
        ~gdf.geometry.x.between(lon_min, lon_max)
        | ~gdf.geometry.y.between(lat_min, lat_max)
    ]
    if not fuera.empty:
        print(
            f"  AVISO: {len(fuera)} punto(s) caen fuera de El Salvador. "
            "Revisa si lat/lon vienen invertidas en esas filas."
        )


def escribir(gdf: gpd.GeoDataFrame, salida: Path) -> None:
    salida.mkdir(parents=True, exist_ok=True)

    gpkg = salida / f"{NOMBRE_CAPA}.gpkg"
    gdf.to_file(gpkg, layer=NOMBRE_CAPA, driver="GPKG")
    print(f"  {gpkg}")

    geojson = salida / f"{NOMBRE_CAPA}.geojson"
    gdf.to_file(geojson, driver="GeoJSON")
    print(f"  {geojson}")

    carpeta_shp = salida / "shapefile"
    carpeta_shp.mkdir(exist_ok=True)
    shp = carpeta_shp / f"{NOMBRE_CAPA}.shp"
    gdf.rename(columns=CAMPOS_SHP).to_file(shp, driver="ESRI Shapefile", encoding="utf-8")
    print(f"  {shp}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "excel",
        nargs="?",
        default="datos/base_unificada_osm_san_salvador.xlsx",
        type=Path,
        help="ruta del Excel de entrada",
    )
    p.add_argument("-o", "--salida", default=Path("salida"), type=Path, help="carpeta de salida")
    p.add_argument("--hoja", default=0, help="nombre o indice de la hoja (por defecto la primera)")
    args = p.parse_args()

    if not args.excel.exists():
        sys.exit(f"ERROR: no existe {args.excel}")

    hoja = int(args.hoja) if str(args.hoja).isdigit() else args.hoja
    df = cargar(args.excel, hoja)
    print(f"Leidas {len(df)} filas de {args.excel}")

    validas, descartadas = limpiar(df)
    validas = enriquecer(validas)

    if not descartadas.empty:
        ruta_desc = args.salida / "filas_descartadas.csv"
        args.salida.mkdir(parents=True, exist_ok=True)
        descartadas.to_csv(ruta_desc, index=False, encoding="utf-8")
        print(f"Descartadas {len(descartadas)} filas -> {ruta_desc}")
        print(descartadas["motivo_descarte"].value_counts().to_string())

    gdf = gpd.GeoDataFrame(
        validas,
        geometry=gpd.points_from_xy(validas.longitud, validas.latitud),
        crs=CRS_SALIDA,
    )
    avisar_fuera_de_bbox(gdf)

    print(f"Capa de puntos: {len(gdf)} puntos en {CRS_SALIDA}")
    escribir(gdf, args.salida)


if __name__ == "__main__":
    main()
