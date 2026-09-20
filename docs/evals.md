# EVALS OCR

Bake-off reproducible de motores **sin subir facturas a git**. El oro y los informes viven en el data-dir.

## Qué mide (dos capas)

1. **Calidad del OCR** — ¿aparecen en el texto los tokens y campos de oro (NIF, número, fecha, importes)?
2. **Calidad del parser** — ¿`parse_invoice` extrae esos campos? Un OCR perfecto con parser ciego no se atribuye al modelo.

Métricas por caso × motor:

| Métrica | Definición |
| --- | --- |
| Token recall | Fracción de `must_tokens` hallados (NIF con/sin guión, importes `13,86`/`13.86`, fuzzy Levenshtein ≥ 0,86) |
| Campos en OCR | Fracción de campos fiscales presentes como subcadena normalizada en el texto |
| Exactitud parser | Fracción de campos iguales al oro (NIF normalizado, fecha ISO, importe ±0,01 €) |
| Latencia | `perf_counter` de `transcribe()` en esta máquina |

`pdf-native` **no puntúa** fotos ni PNG: se marca `skipped`, no como fallo.

## Motores

| id | Qué es | Default ingest |
| --- | --- | --- |
| `native` | Capa de texto PDF (PyMuPDF) | sí, si calidad ≥ 0,65 |
| `vision` | Vision.framework de macOS | auto en Mac (fotos) |
| `rapid` | RapidOCR ONNX (PP-OCR) | auto en Windows/Linux; fallback en Mac |
| `deepseek` | DeepSeek-OCR vía Ollama | no (`--ocr deepseek`) |
| `tesseract` | CLI `tesseract` si está instalado | no |
| `unlimited` | Unlimited-OCR HTTP/GGUF | no |
| `paddle` | PaddleOCR-VL si el flag está on | no |

No hay Azure ni APIs cloud. No se “compran” pesos de pago: RapidOCR descarga ONNX locales al primer uso; Vision no descarga nada.

## Set de oro

- **Real** (fuera de git): `<data-dir>/evals/gold.json` apunta a ficheros en `archivo/`. No copies ese JSON al repo: tiene NIF y números de factura reales.
- **Sintético** (siempre, `--synthetic`): PDF vectorial + PNG raster de una factura demo Iberdrola (`B12345674`). Control positivo: `native` debe ir al 100 % en el PDF digital.

Añadir un caso real:

```json
{
  "version": 1,
  "cases": [
    {
      "id": "ejemplo",
      "path": "archivo/CI-VA-001/2026/09/gasto/hogar/foto.jpg",
      "kind": "photo",
      "fields": {
        "emisor_contains": ["LEROY"],
        "nif_emisor": "B84818442",
        "numero": "064-0009-720394",
        "fecha": "2026-09-18",
        "base": "11.45",
        "iva_cuota": "2.41",
        "total": "13.86"
      },
      "must_tokens": ["LEROY MERLIN", "064-0009-720394", "13,86"]
    }
  ]
}
```

`kind`: `photo` | `raster` | `scan-pdf` | `digital-pdf`.

## Cómo correrlo

```bash
export AEAT_HUB_DATA_DIR=/Volumes/SSDCX9/data/aeat-hub
uv run aeat-hub ocr-status
uv run aeat-hub eval
uv run aeat-hub eval --engines native,rapid,vision
uv run aeat-hub eval --no-synthetic
```

Escribe:

- `evals/eval-AAAAMMDD-HHMMSS.json`
- `logs/eval-AAAAMMDD-HHMMSS.log`

n pequeño (2 tickets reales + 2 sintéticos) **no** generaliza a todas las facturas españolas; sí decide el motor para *esta* muestra y esta máquina (M1 Pro 16 GB).

## Interpretar el ranking

Orden: campos en OCR → token recall → parser → menor latencia. El ranking responde “¿qué motor lee mejor los campos fiscales?”, no “¿cuál es el VLM más grande?”.
