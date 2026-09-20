# AEAT Hub

Libros locales de **ingresos y gastos** para autónomos y arrendadores en España.
No presenta modelos a Hacienda: es el libro auxiliar para no perder facturas, no
duplicarlas y poder defender cada asiento.

Esto **no es software oficial de la AEAT**. Revisa los asientos antes de declarar.

## Qué hace (MVP)

- Varios expedientes por titular: `capital_inmobiliario` (alquiler) y `actividad_economica`.
- Inbox de PDF y fotos (móvil). Extrae NIF, fecha, número, bases e IVA.
- Deduplica a tres niveles: mismo fichero, misma factura fiscal, sospechosos (importe±3 días o foto casi igual).
- Clasifica por proveedor/palabras clave. Si reclasificas, **aprende** (regla por NIF emisor).
- SQLite como fuente de verdad. Excel como exportación reproducible.
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
  inbox/ processed/ rejected/ db/ledger.sqlite exports/
```

Cámbialo con `--data-dir` o `AEAT_HUB_DATA_DIR`. Ver `.env.example` y [SECURITY.md](SECURITY.md).

```bash
export AEAT_HUB_DATA_DIR=/Volumes/SSDCX9/data/aeat-hub
uv run aeat-hub init --titular "Tu nombre" --nif 12345678Z
# deja PDF/JPG en $AEAT_HUB_DATA_DIR/inbox
uv run aeat-hub ingest --actividad CI-VA-001
uv run aeat-hub pendientes --actividad CI-VA-001
uv run aeat-hub reclasificar 1 CI.MEJ.PVC
uv run aeat-hub duplicados --actividad CI-VA-001
uv run aeat-hub export --actividad CI-VA-001 --year 2026 --xlsx
```

`12345678Z` es un NIF de ejemplo (dígito de control válido). Usa el tuyo solo en el data-dir.

## OCR

Cascada por defecto, pensada para un **M1 Pro 16 GB sin NVIDIA**:

1. Texto nativo del PDF (Iberdrola, comunidad, seguros…).
2. [RapidOCR](https://github.com/RapidAI/RapidOCR) (ONNX) para fotos y escaneos.

[Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR) de Baidu es un transcriptor
excelente en GPU NVIDIA (PDF largos, un solo pase), pero **no extrae JSON de factura
española** y el camino oficial es CUDA. En Apple Silicon 16 GB es experimental
(GGUF / llama.cpp). Queda como proveedor opcional:

```bash
uv run aeat-hub ocr-status
# si tienes un servidor OpenAI-compatible con el modelo:
export AEAT_HUB_UNLIMITED_OCR_URL=http://127.0.0.1:8080/v1/chat/completions
uv run aeat-hub ingest --actividad CI-VA-001 --ocr unlimited
```

Si Unlimited-OCR no carga, el CLI avisa y sigue con RapidOCR.

PaddleOCR-VL (más pesado) se activa con `AEAT_HUB_PADDLEOCR_VL=1` y `--ocr paddle`.

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

Los tests usan facturas sintéticas. No hace falta GPU ni descargar Unlimited-OCR.

## Licencia

MIT. Ver [LICENSE](LICENSE).
