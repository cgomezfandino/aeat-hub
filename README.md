# AEAT Hub

Libros locales de **ingresos y gastos** para autónomos y arrendadores en España.
No presenta modelos a Hacienda: es el libro auxiliar para no perder facturas, no
duplicarlas y poder defender cada asiento.

Esto **no es software oficial de la AEAT**. Revisa los asientos antes de declarar.

**Documentación completa:** [docs/README.md](docs/README.md) (arquitectura, fiscalidad, CLI, OCR, archivo en disco, código y hoja de ruta).

## Qué hace (MVP)

- Varios expedientes por titular: `capital_inmobiliario` (alquiler) y `actividad_economica`.
- Inbox de PDF y fotos (móvil). Tras clasificar, el fichero queda en `archivo/<expediente>/<año>/<mes>/<gasto|ingreso|mejora>/<rubro>/`.
- Extrae NIF, fecha, número, bases e IVA.
- Deduplica a tres niveles: mismo fichero, misma factura fiscal, sospechosos (importe±3 días o foto casi igual).
- Clasifica por proveedor/palabras clave. Si reclasificas, **aprende** (regla por NIF emisor).
- SQLite como fuente de verdad. El dashboard HTML y el Excel son **fotos** del ejercicio: se ven, se filtran y se exportan; **no escriben** la base. Validar o cambiar rubro es cosa del CLI (`validar`, `reclasificar`).
- 100 % local. Las facturas reales **no van a git**.

El primer expediente semilla es un **alquiler en Valladolid** (luz, agua, internet,
comunidad, seguros, hogar, mejoras PVC/solado/revestimiento/mano de obra, rentas e indemnizaciones).

## Requisitos

- Python 3.12+
- macOS o Linux. Probado como objetivo: MacBook Apple Silicon.
- [uv](https://docs.astral.sh/uv/)

## Instalación

```bash
git clone https://github.com/cgomezfandino/aeat-hub.git
cd aeat-hub
uv sync
```

Fotos HEIC del iPhone:

```bash
uv sync --extra heic
```

## Datos (fuera del repo)

Por defecto:

```
/Volumes/SSDCX9/data/aeat-hub/
  inbox/                 # suelta aquí PDF y fotos
  archivo/               # queda ordenado tras el ingest
    CI-VA-001/
      2026/
        03/
          gasto/luz/
          gasto/agua/
          ingreso/renta/
          mejora/pvc/
          pendiente/sin-cuenta/
  rejected/hash/         # mismo fichero (SHA-256)
  db/ledger.sqlite
  exports/
```

Cámbialo con `--data-dir` o `AEAT_HUB_DATA_DIR`. Ver `.env.example` y [SECURITY.md](SECURITY.md).

```bash
export AEAT_HUB_DATA_DIR=/Volumes/SSDCX9/data/aeat-hub
uv run aeat-hub init --titular "Tu nombre" --nif 12345678Z
# deja PDF/JPG en $AEAT_HUB_DATA_DIR/inbox
uv run aeat-hub ingest --actividad CI-VA-001
uv run aeat-hub pendientes --actividad CI-VA-001
uv run aeat-hub reclasificar 1 Ventanas   # nombre de rubro; mueve el fichero
uv run aeat-hub validar 2                 # el modelo acertó; cierra el asiento
uv run aeat-hub dashboard --actividad CI-VA-001 --year 2026
# El HTML abre el libro del año (pestañas Revisar / Libro / Resumen) y regenera el Excel.
# Tras validar o reclasificar, vuelve a generar el dashboard para ver la foto nueva.
```

`12345678Z` es un NIF de ejemplo (dígito de control válido). Usa el tuyo solo en el data-dir.

## OCR

Cascada por defecto (`--ocr auto`):

1. Texto nativo del PDF (Iberdrola, comunidad, seguros…).
2. Fotos/escaneos: **Apple Vision en macOS**, **RapidOCR (ONNX) en Windows/Linux** (y en Mac si Vision no está).

DeepSeek-OCR (Ollama) y Unlimited-OCR son opcionales (`--ocr deepseek` / `--ocr unlimited`).
No son el default: Vision/RapidOCR no piden 7 GB extra.

```bash
uv run aeat-hub ocr-status
ollama pull deepseek-ocr   # opcional
uv run aeat-hub ingest --actividad CI-VA-001 --ocr deepseek
```

Bake-off local (oro y resultados en el data-dir, nunca en git):

```bash
uv run aeat-hub eval
```

Metodología: [docs/evals.md](docs/evals.md).

## Modelo fiscal (resumen)

Alquiler de vivienda habitual del arrendador: **rendimientos de capital inmobiliario**
(LIRPF). Las **mejoras** (ventanas PVC, solado, revestimiento) no son gasto del año:
se capitalizan. Si el sistema duda entre reparación y mejora, deja el asiento
`pendiente` para que lo reclasifiques.

Una actividad económica (autónomo) es otro expediente, con IVA. El CLI exige
`--actividad` para no mezclar libros.

## Tests

```bash
uv run pytest
```

Los tests usan facturas sintéticas. No hace falta GPU ni descargar Unlimited-OCR. Guía: [docs/desarrollo.md](docs/desarrollo.md).

## Licencia

MIT. Ver [LICENSE](LICENSE). Seguridad de datos: [SECURITY.md](SECURITY.md).
