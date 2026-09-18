#!/usr/bin/env python3
"""Convierte un archivo SPSS (.sav) a Excel (.xlsx).

Uso:
    python sav_to_excel.py entrada.sav [salida.xlsx]

Si no se indica el archivo de salida, se usa el mismo nombre que el de
entrada cambiando la extensión a .xlsx.

Requiere: pyreadstat, pandas, openpyxl
    pip install -r requirements.txt
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyreadstat


def convert_sav_to_excel(input_path: Path, output_path: Path, apply_value_labels: bool = True) -> None:
    df, meta = pyreadstat.read_sav(str(input_path), apply_value_formats=apply_value_labels)

    # Usa las etiquetas de columna (si existen) como nombre de columna en Excel.
    column_labels = {
        col: (label if label else col)
        for col, label in zip(meta.column_names, meta.column_labels)
    }
    df = df.rename(columns=column_labels)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Datos")

    print(f"Archivo convertido: {input_path} -> {output_path}")
    print(f"Filas: {len(df)}, Columnas: {len(df.columns)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convierte un archivo .sav (SPSS) a Excel (.xlsx)")
    parser.add_argument("entrada", type=Path, help="Ruta del archivo .sav de entrada")
    parser.add_argument(
        "salida",
        type=Path,
        nargs="?",
        help="Ruta del archivo .xlsx de salida (por defecto: mismo nombre con extensión .xlsx)",
    )
    parser.add_argument(
        "--sin-etiquetas",
        action="store_true",
        help="No aplicar las etiquetas de valores (deja los códigos numéricos/crudos)",
    )
    args = parser.parse_args()

    input_path: Path = args.entrada
    if not input_path.exists():
        print(f"Error: no se encontró el archivo '{input_path}'", file=sys.stderr)
        sys.exit(1)

    output_path: Path = args.salida if args.salida else input_path.with_suffix(".xlsx")

    convert_sav_to_excel(input_path, output_path, apply_value_labels=not args.sin_etiquetas)


if __name__ == "__main__":
    main()
