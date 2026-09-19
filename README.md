# EMPRESAS

Búsqueda y descarga de registros de empresas desde **Google Maps** para el
**distrito de San Salvador** (El Salvador), usando la *Places API (New)* de Google.

El script `buscar_empresas.py`:

1. Obtiene los límites geográficos del distrito (Geocoding API, con respaldo
   de coordenadas predefinidas).
2. Divide el área en una **grilla de celdas** y ejecuta una búsqueda de texto
   por cada celda × categoría (la API devuelve máximo 60 resultados por
   consulta, por eso se recorre por celdas).
3. **Deduplica** por `place_id` y filtra por dirección.
4. Exporta a **CSV, XLSX, JSON y GeoJSON**.

## 1. Requisitos

```bash
pip install -r requirements.txt
```

En [Google Cloud Console](https://console.cloud.google.com/):

- Cree un proyecto y active la **facturación** (la Places API es de pago).
- Habilite **Places API (New)** y, opcionalmente, **Geocoding API**.
- Cree una **API key** en *APIs y servicios → Credenciales*.

## 2. Configuración de la clave

```bash
cp .env.example .env     # y edite el valor
# o bien:
export GOOGLE_MAPS_API_KEY="su_api_key"
```

`.env` está en `.gitignore`: no suba la clave al repositorio.

## 3. Uso

```bash
# Estimar cuántas peticiones y cuánto costaría, sin consultar nada
python buscar_empresas.py --dry-run

# Prueba pequeña (3 celdas, 2 categorías)
python buscar_empresas.py --limite-celdas 3 --categorias "restaurante,farmacia"

# Descarga completa del distrito
python buscar_empresas.py

# Otra área (p. ej. el distrito de San Salvador, Cusco, Perú)
python buscar_empresas.py --distrito "San Salvador, Cusco, Perú" --region PE \
    --filtro-direccion "San Salvador" --prefijo empresas_san_salvador_cusco
```

### Opciones principales

| Opción | Descripción | Por defecto |
|---|---|---|
| `--distrito` | Área a consultar (se geocodifica) | `Distrito de San Salvador, San Salvador, El Salvador` |
| `--bbox` | Rectángulo manual `sur,oeste,norte,este` | — |
| `--paso` | Lado de cada celda en metros (menor = más cobertura y más costo) | `1000` |
| `--categorias` | Lista separada por comas | catálogo interno de 30 categorías |
| `--filtro-direccion` | Conserva solo direcciones que contengan el texto (`''` desactiva) | `San Salvador` |
| `--max-paginas` | Páginas por consulta (1–3, 20 resultados c/u) | `3` |
| `--formatos` | `csv`, `xlsx`, `json`, `geojson` | `csv,xlsx,json` |
| `--salida` / `--prefijo` | Carpeta y prefijo de los archivos | `datos` / `empresas_san_salvador` |
| `--limite-celdas` | Procesa solo las primeras N celdas (pruebas) | — |
| `--dry-run` | Solo estima peticiones y costo | — |
| `--si` | Omite la confirmación en búsquedas grandes (uso desatendido) | — |
| `--umbral-confirmacion` | Peticiones a partir de las cuales se pide confirmación | `500` |

## 4. Columnas exportadas

`place_id`, `nombre`, `categoria_consultada`, `tipo_principal`, `tipos`,
`estado_negocio`, `direccion`, `direccion_corta`, `municipio`, `departamento`,
`pais`, `codigo_postal`, `latitud`, `longitud`, `plus_code`,
`telefono_nacional`, `telefono_internacional`, `sitio_web`, `url_google_maps`,
`calificacion`, `total_resenas`, `nivel_precio`, `abierto_ahora`, `horario`,
`fecha_extraccion`.

## 5. Costo y buenas prácticas

- Cada consulta puede generar hasta 3 peticiones facturables. Con la grilla por
  defecto son cientos de peticiones: **ejecute siempre `--dry-run` primero** y
  fije un *presupuesto/alerta de facturación* y cuotas diarias en Google Cloud.
- Reduzca costo recortando `--categorias`, subiendo `--paso` o bajando
  `--max-paginas`.
- Si la estimación supera `--umbral-confirmacion` peticiones, el script pide
  confirmación antes de gastar (use `--si` para ejecuciones desatendidas).
- El script reintenta ante errores de red y HTTP 429/5xx, y si lo interrumpe
  con `Ctrl+C` exporta lo recolectado hasta ese momento.
- Los datos provienen de la API oficial de Google. Su uso está sujeto a los
  [Términos de Servicio de Google Maps Platform](https://cloud.google.com/maps-platform/terms)
  (entre otros, límites de almacenamiento y redistribución del contenido).
  Este script **no** hace *scraping* del sitio web de Google Maps.
