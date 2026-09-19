#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Revisa que frontera(s) devuelve OpenStreetMap para un distrito.

Sirve para diagnosticar cuando un archivo descargar_<distrito>.py se queja
de que no encuentra la frontera, o de que encuentra mas de una.

Uso:   python3 revisar_frontera.py Ayutuxtepeque
       python3 revisar_frontera.py "Santa Tecla|Nueva San Salvador"

Imprime cada relacion que casa con el patron, con su id, su nombre, su
admin_level y su centro, diciendo cual cae dentro de El Salvador. Con eso se
ve de inmediato si el PATRON hay que afinarlo y a que area apunta cada una.

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import sys
import time

import requests

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python3 revisar_frontera.py <PATRON>\n"
                         "Ejemplo: python3 revisar_frontera.py Ayutuxtepeque")
    patron = sys.argv[1]

    consulta = (
        '[out:json][timeout:180];\n'
        'rel(%s)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]'
        '["name"~"^(%s)$"];\nout tags center;'
    ) % (BBOX_PAIS, patron)
    print("Consulta enviada:\n%s\n" % consulta)

    datos = None
    for intento in range(3):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=300,
                              headers={"User-Agent": "empresas-sv/1.0"})
            if r.status_code == 200:
                datos = r.json()
                break
            print("   %s respondio %d" % (servidor, r.status_code))
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))
        time.sleep(10 * (2 ** intento))
    if datos is None:
        raise SystemExit("Overpass no respondio. Intenta de nuevo mas tarde.")

    sur, oeste, norte, este = [float(x) for x in BBOX_PAIS.split(",")]
    relaciones = [e for e in datos.get("elements", []) if e.get("type") == "relation"]
    if not relaciones:
        print("NINGUNA relacion casa con '%s'." % patron)
        print("Revisa como esta escrito el nombre en OpenStreetMap; puede llevar")
        print("tilde, un nombre antiguo, o estar como 'Distrito de ...'.")
        return

    print("%d relacion(es) casan con '%s':\n" % (len(relaciones), patron))
    dentro = 0
    for relacion in relaciones:
        tags = relacion.get("tags", {})
        centro = relacion.get("center", {})
        lat, lon = centro.get("lat"), centro.get("lon")
        if lat is None:
            ubicacion, en_pais = "sin centro", False
        else:
            en_pais = sur <= lat <= norte and oeste <= lon <= este
            ubicacion = "%.4f, %.4f" % (lat, lon)
        dentro += en_pais
        print("  relacion %-12s admin_level=%-4s %-28s %s  %s"
              % (relacion["id"], tags.get("admin_level", "?"),
                 tags.get("name", ""), ubicacion,
                 "<- dentro de El Salvador" if en_pais else "(fuera del pais)"))
        print("     area(%d)   https://www.openstreetmap.org/relation/%s"
              % (3600000000 + relacion["id"], relacion["id"]))

    print()
    if dentro == 0:
        print("PROBLEMA: ninguna cae dentro de El Salvador; el script se detendra.")
    elif dentro == 1:
        print("Todo bien: queda exactamente una dentro del pais.")
    else:
        print("PROBLEMA: quedan %d dentro del pais, el script no adivina cual usar." % dentro)
        print("Afina el PATRON del archivo para que case solo con la correcta,")
        print("mirando los enlaces de arriba para saber cual es.")


if __name__ == "__main__":
    main()
