# OCR

El objetivo no es “el mejor modelo del mundo”, sino **leer facturas españolas en un M1 Pro 16 GB sin NVIDIA**, sin mandar documentos a la nube.

## Cascada por defecto (`--ocr auto`)

Elige sola, según el fichero y el SO:

1. **Todo se rasteriza y se lee con OCR de imagen**, también los PDF digitales: la capa de texto embebida de muchos escaneos desordena líneas e importes (commit 9ea8cae). El texto nativo (`pymupdf`) solo se usa si se pide (`--ocr native`) o si el OCR de imagen no está disponible.
2. **Motor de imagen:**
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

### Google Gemini (`--ocr gemini`)

Proveedor multimodal opcional de alta precisión para facturas complejas o escaneos con tablas de artículos difíciles.
Utiliza **Gemini 2.5 Flash** (`gemini-2.5-flash`). Es el modelo que queda tras comparar Flash Lite en el set de oro: Lite sale más barato y pierde NIF de receptor e importes del ticket. Para cambiarlo: `AEAT_HUB_GEMINI_MODEL`.

Configuración en `.env`:
```bash
GEMINI_API_KEY=tu-api-key-de-google
# o bien
GOOGLE_API_KEY=tu-api-key-de-google
```

Ejecución vía CLI:
```bash
uv run aeat-hub ingest --actividad CI-VA-001 --ocr gemini
```

Gemini devuelve directamente el JSON fiscal, con un `responseSchema` que fija los campos y los valores permitidos (temperatura 0). Prompt en `ocr/gemini.py` (`INVOICE_PROMPT`), redactado sobre los art. 6, 7 y 15 del RD 1619/2012:

- **Tipo de documento:** `completa`, `simplificada`, `rectificativa` o `no_factura`. Presupuestos, albaranes, proformas y recibos no son facturas: se marcan y nunca se consolidan solos.
- **Campos:**
  - serie separada del número;
  - fecha de operación solo si difiere de la de expedición;
  - moneda ISO;
  - desglose por tipo con recargo de equivalencia;
  - retención IRPF;
  - mención legal: exenta art. 20, inversión del sujeto pasivo, criterio de caja, no sujeta o régimen especial;
  - rectificativa con método (sustitución o diferencias) y causa;
  - `campos_dudosos`, la lista de campos ilegibles según el propio modelo.
- **Sin cálculos inventados:** si el documento no muestra IVA, queda vacío (nunca un 21 % por defecto).
- **Respuesta rechazada:** si `finishReason` no es `STOP` (respuesta cortada), no se parsea.
- **API key** en la cabecera `x-goog-api-key`, nunca en la URL.

La confianza de la extracción no es fija. Se calcula con comprobaciones: NIF con control válido, total que cuadra (base + IVA + recargo − retención) y campos dudosos. Un `no_factura` queda en ≤ 0,3. El ingest manda a revisión cualquier documento `no_factura`, en moneda distinta del euro o con campos dudosos, con el aviso correspondiente.

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
