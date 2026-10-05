#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Corre, uno tras otro, los 18 scripts de descarga del distrito de APOPA y al
final une todos los resultados en un solo archivo:

    datos/todos_apopa.csv

Uso:   pip install requests
       python3 correr_todo_apopa.py

Tiene que estar en la misma carpeta que los 18 archivos
descargar_<categoria>_apopa.py. Tarda alrededor de 20 a 30 minutos en total.

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import csv
import glob
import os
import subprocess
import sys

CARPETA = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(CARPETA, "datos")
SALIDA = os.path.join(DATOS, "todos_apopa.csv")

CATEGORIAS = ["shop", "office", "craft", "brand", "industrial", "amenity",
              "leisure", "tourism", "sport", "cuisine", "club", "healthcare",
              "building", "landuse", "place", "natural", "historic",
              "man_made"]


def main():
    fallaron = []
    for numero, categoria in enumerate(CATEGORIAS, 1):
        script = "descargar_%s_apopa.py" % categoria
        print("\n" + "=" * 70)
        print("[%d/%d] %s" % (numero, len(CATEGORIAS), script))
        print("=" * 70, flush=True)
        if not os.path.exists(os.path.join(CARPETA, script)):
            print("   no se encontro %s en esta carpeta" % script)
            fallaron.append(categoria)
            continue
        # Se corre parado en la carpeta de Apopa, para que todos dejen sus
        # resultados en apopa/datos/ y compartan la frontera ya descargada.
        resultado = subprocess.run([sys.executable, script], cwd=CARPETA)
        if resultado.returncode != 0:
            fallaron.append(categoria)

    # Une todos los CSV de Apopa en uno solo (tienen las mismas columnas).
    archivos = sorted(f for f in glob.glob(os.path.join(DATOS, "*_apopa.csv"))
                      if os.path.abspath(f) != SALIDA)
    total = 0
    if archivos:
        with open(SALIDA, "w", newline="", encoding="utf-8-sig") as salida:
            escritor = None
            for archivo in archivos:
                with open(archivo, newline="", encoding="utf-8-sig") as fh:
                    lector = csv.DictReader(fh)
                    if escritor is None:
                        escritor = csv.DictWriter(salida, fieldnames=lector.fieldnames)
                        escritor.writeheader()
                    for fila in lector:
                        escritor.writerow(fila)
                        total += 1

    print("\n" + "=" * 70)
    print("LISTO")
    print("=" * 70)
    print("Categorias descargadas: %d de %d" % (len(CATEGORIAS) - len(fallaron),
                                                len(CATEGORIAS)))
    if fallaron:
        print("No terminaron bien: %s" % ", ".join(fallaron))
        print("Puedes volver a correr solo esos, por ejemplo:")
        print("    python3 descargar_%s_apopa.py" % fallaron[0])
    if archivos:
        print("\nArchivo unido: %s (%d filas)" % (SALIDA, total))
    else:
        print("\nNo se genero ningun CSV, no hay nada que unir.")


if __name__ == "__main__":
    main()
