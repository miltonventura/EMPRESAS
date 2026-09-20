# EMPRESAS
Búsqueda de empresas

## `waze_feasibility.py`

Herramienta de **evaluación** (no de extracción) que responde a: ¿se pueden
descargar datos de empresas, restaurantes y otras categorías desde Waze?

Sondea los endpoints públicos y semipúblicos del Live Map de Waze, mide qué
devuelve cada uno (registros, campos, categorías, límites), prueba la cobertura
por rubro y emite un veredicto técnico junto con el análisis de viabilidad legal
y las alternativas oficiales. Sin dependencias: solo biblioteca estándar.

```bash
python3 waze_feasibility.py --self-test                      # valida la lógica, sin red
python3 waze_feasibility.py --solo-legal                     # solo análisis legal, sin red
python3 waze_feasibility.py --ciudad "CDMX" --lat 19.4326 --lon -99.1332 \
        --json informe.json --markdown informe.md            # sondeo completo
```

Códigos de salida: `0` viable · `1` parcial · `2` no viable · `3` error de uso.
