"""Genera un código QR (PNG) a partir de un enlace.

Uso:
    pip install "qrcode[pil]"
    python scripts/generar_qr.py <enlace> <salida.png>
"""
import sys

import qrcode


def main():
    if len(sys.argv) != 3:
        sys.exit("Uso: python scripts/generar_qr.py <enlace> <salida.png>")
    url, salida = sys.argv[1], sys.argv[2]
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(salida)
    print(f"QR guardado en {salida} -> {url}")


if __name__ == "__main__":
    main()
