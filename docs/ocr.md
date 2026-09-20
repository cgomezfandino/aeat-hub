# OCR

El objetivo no es “el mejor modelo del mundo”, sino **leer facturas españolas en un M1 Pro 16 GB sin NVIDIA**, sin mandar documentos a la nube.

## Cascada por defecto (`--ocr auto`)

Elige sola, según el fichero y el SO:

1. **PDF nativo** (`pymupdf`): si hay capa de texto usable (NIF, IVA, FACTURA, importes). Umbral ~0,65. Igual en Mac, Windows y Linux.
2. **Fotos / escaneos:**
   - **macOS:** Apple Vision (nativo del sistema). Si falla, RapidOCR.
   - **Windows / Linux:** RapidOCR (ONNX). Portable, sin Vision.

## Dual Vision + RapidOCR (`aeat-hub dual`)

`auto` elige **un** motor. `dual` corre Vision y RapidOCR en paralelo, vota campo a campo y saca un Excel de discrepancias. No escribe asientos.

- **acuerdo** — mismo NIF / fecha / número / importe (±0,01 €).
- **solo un motor** — se propone ese valor.
- **conflicto** — no se promedia. Un NIF con dígito válido gana si el otro no lo es. Si no, vacío y a revisar.
- Campos críticos (NIF emisor, número, fecha, total) en conflicto → recomendación `revisar`.

En Windows/Linux Vision no existe: el dual queda incompleto; el ingest portable sigue siendo RapidOCR.

```bash
uv run aeat-hub dual
```

## Por qué Unlimited-OCR no es el default

[baidu/Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR) es un transcriptor muy fuerte en documentos largos (OmniDocBench alto, un pase de muchas páginas). En este proyecto:

- El camino oficial es **CUDA + Transformers/vLLM/SGLang**.
- En Mac solo hay vías experimentales (GGUF / llama.cpp / parches MPS) y 16 GB quedan justos.
- El modelo saca **Markdown**, no un JSON de factura española. El parser de NIF/IVA hay que construirlo igual encima.

Queda como proveedor **opcional y no bloqueante**.

## Proveedores opcionales

### Unlimited-OCR (`--ocr unlimited`)

Necesitas **una** de estas:

```bash
export AEAT_HUB_UNLIMITED_OCR_URL=http://127.0.0.1:8080/v1/chat/completions
# o
export AEAT_HUB_UNLIMITED_OCR_GGUF=/ruta/Unlimited-OCR-Q4_K_M.gguf
export AEAT_HUB_UNLIMITED_OCR_MMPROJ=/ruta/mmproj-Unlimited-OCR-F16.gguf
# llama-mtmd-cli o llama-cli en PATH
```

Si no está disponible, el CLI avisa y sigue con la cascada local.

### PaddleOCR-VL (`--ocr paddle`)

```bash
export AEAT_HUB_PADDLEOCR_VL=1
# además hay que instalar paddleocr por tu cuenta; no va en las deps por defecto
```

Pesado en 16 GB. Misma política: si falla, cascada local.

### DeepSeek-OCR vía Ollama (`--ocr deepseek`)

No es Unlimited-OCR de Baidu: es el modelo de la biblioteca de Ollama (`deepseek-ocr`, ~6,7 GB). Local, sin nube.

```bash
ollama serve
ollama pull deepseek-ocr
uv run aeat-hub ingest --actividad CI-VA-001 --ocr deepseek
```

Variables: `AEAT_HUB_OLLAMA_URL` (default `http://127.0.0.1:11434`) y `AEAT_HUB_OLLAMA_OCR_MODEL` (default `deepseek-ocr`). Si Ollama no está o falta el modelo, cascada local. En 16 GB va justo; no es el auto.

### Apple Vision (`--ocr vision`)

En macOS usa Vision.framework (reconocimiento `accurate`, `es-ES`). Compila un binario local con `swiftc` la primera vez. No descarga pesos. Si `swiftc` falla, cascada local.

### Tesseract (`--ocr tesseract`)

Si tienes `tesseract` en PATH (`brew install tesseract tesseract-lang`). Si no, cascada local.

Comprobar:

```bash
uv run aeat-hub ocr-status
uv run aeat-hub eval
```

Metodología y métricas: [evals.md](evals.md).

## Fotos HEIC (iPhone)

```bash
uv sync --extra heic
```

Sin `pillow-heif`, un `.heic` falla con un mensaje pidiendo ese extra.

## Qué extrae el parser (después del OCR)

Sobre el texto plano, de forma heurística (no es un VLM):

- NIF/CIF/NIE del emisor (y receptor si hay un segundo), con dígito de control.
- Número de factura, fecha (día primero).
- Base imponible, tipo IVA (21/10/4/0 si encaja), cuota, total.
- Nombre de emisor (línea anterior al NIF).

Importes en formato español (`1.234,56`) o anglosajón. Confianza del extracto: suma de campos encontrados (máx. 0,99).

Azure Document Intelligence y APIs tipo FacturaHub **no** se usan (nube).
