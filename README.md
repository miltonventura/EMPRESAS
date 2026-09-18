# EMPRESAS
Búsqueda de empresas

## Conversión de SAV a Excel

`sav_to_excel.py` convierte un archivo SPSS (`.sav`) a Excel (`.xlsx`),
conservando las etiquetas de columnas y de valores cuando existen.

```bash
pip install -r requirements.txt
python sav_to_excel.py entrada.sav [salida.xlsx]
```

Usa `--sin-etiquetas` para exportar los códigos crudos en lugar de las
etiquetas de valor.
