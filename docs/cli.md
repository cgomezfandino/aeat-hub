# CLI

Binario: `aeat-hub` (Typer). Siempre puedes pasar `--data-dir` o exportar `AEAT_HUB_DATA_DIR`.

```bash
export AEAT_HUB_DATA_DIR=/Volumes/SSDCX9/data/aeat-hub
uv run aeat-hub --help
uv run aeat-hub --version
```

## Comandos

### `init`

Crea carpetas, `ledger.sqlite`, plan de cuentas y el expediente `CI-VA-001`.

```bash
uv run aeat-hub init --titular "Tu nombre" --nif 12345678Z
```

| Opción | Default | Notas |
| --- | --- | --- |
| `--data-dir` | `AEAT_HUB_DATA_DIR` o `/Volumes/SSDCX9/data/aeat-hub` | Fuera del git |
| `--titular` | `Titular local` | |
| `--nif` | `00000000T` | Marcador válido; cámbialo. No lo subas a git |

Idempotente a efectos de esquema: volver a ejecutarlo no borra asientos.

### `actividad alta` / `actividad listar`

```bash
uv run aeat-hub actividad listar
uv run aeat-hub actividad alta \
  --nombre "Taller" \
  --regimen actividad_economica \
  --codigo AE-TALLER
```

`--regimen` es `capital_inmobiliario` o `actividad_economica`. Si omites `--codigo`, se genera `CI-00N` / `AE-00N`.

### `actividad titulo`

Personaliza la cabecera del libro (expediente, titular, inmueble). El código `CI-VA-001` y el régimen fiscal no cambian. También puedes hacerlo con el lápiz de la cabecera del dashboard.

```bash
uv run aeat-hub actividad titulo --actividad CI-VA-001 \
  --nombre "Alquiler piso Centro" \
  --titular "Tu nombre" \
  --inmueble "Piso VA"
```

Luego regenera el HTML: `aeat-hub dashboard --actividad CI-VA-001 --year 2026`.

### `cuenta alta` / `cuentas`

```bash
uv run aeat-hub cuenta alta --nombre Pintura --casilla reparacion
uv run aeat-hub cuentas
uv run aeat-hub cuentas --regimen capital_inmobiliario
```

`cuenta alta` crea un rubro propio. `--casilla` admite estas claves de `CASILLAS_CI`: `ingresos`, `intereses`, `reparacion`, `ibi`, `comunidad`, `seguros`, `suministros`, `admin`, `otros`, `amortizacion` y `mejoras`.

`cuentas` lista el plan por **nombre**, con columnas `nombre`, `tipo`, `casilla` y `origen` (`sistema` o `usuario`). No muestra identificadores internos.

### `ingest`

Lee el inbox (o un `--path`) , extrae, deduplica, clasifica y **ordena el fichero**.
Si un documento peta, el resto del lote sigue: el fallido va a `rejected/error/` y el traceback queda en `logs/ingest-AAAAMMDD-HHMMSS.log`.

```bash
uv run aeat-hub ingest --actividad CI-VA-001
```

| `--ocr` | Comportamiento |
| --- | --- |
| `auto` (default) | Siempre OCR de imagen: Apple Vision en Mac, RapidOCR si Vision no puede. No usa el texto que incrusta Adobe Scan ni otro programa |
| `native` | Solo la capa de texto del PDF. No es el flujo habitual |
| `rapid` | Fuerza RapidOCR |
| `unlimited` | Intenta Unlimited-OCR; si falla, cascada local |
| `paddle` | Intenta PaddleOCR-VL; si falla, cascada local |
| `vision` | Intenta Apple Vision; si falla, cascada local |
| `deepseek` | Intenta DeepSeek-OCR vía Ollama; si falla, cascada local |
| `tesseract` | Intenta Tesseract CLI; si falla, cascada local |

Extensiones: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.tif`, `.tiff`, `.heic`, `.heif`.

Si `--path` **no** está en el inbox, se **copia** (no se borra el original). Si está en el inbox, se **mueve**.

### `pendientes`

Asientos `pendiente` del expediente (sin cuenta, o cuenta con confianza &lt; 0,8).

```bash
uv run aeat-hub pendientes --actividad CI-VA-001
```

### `duplicados`

Asientos marcados `duplicado` (niveles 2 y 3). El duplicado de fichero (SHA) ni siquiera crea asiento: va a `rejected/hash/`.

### `reclasificar`

```bash
uv run aeat-hub reclasificar 12 Hogar
uv run aeat-hub reclasificar 12 Pintura --solo-este
```

Cambia la cuenta (por **nombre** de rubro), deja el asiento `confirmado` **y validado**, guarda regla por NIF emisor, aplica a otros `pendiente` del mismo NIF (salvo `--solo-este`) y **mueve el PDF** al rubro nuevo.

### `validar`

```bash
uv run aeat-hub validar 12
```

Check humano: el rubro no cambia. `reparse` y un nuevo OCR **no pisan** ese asiento. Sirve cuando el modelo acertó y solo quieres cerrarlo.

### `reabrir`

```bash
uv run aeat-hub reabrir 12
```

Devuelve el asiento a `pendiente` si validar fue un error. El dashboard hace lo mismo: pulsa el botón verde **Validado** (pasa a rojo **Por validar**) o desmarca el check en el lápiz.

### `factura numero`

Corrige el número que leyó el OCR y vuelve a agrupar (mismo emisor + ID = un asiento). Si el total no cuadra, deja las dos facturas en `conflicto`.

```bash
uv run aeat-hub factura numero 12 F2026-000123
uv run aeat-hub factura numero 12 010-000043-004-4843-NFS:055610
```

### `duplicado`

Fusión manual de un duplicado evidente (misma compra con número distinto, o sin número): marca un asiento como duplicado de otro y mueve sus evidencias a la misma factura. También lo desmarca.

```bash
uv run aeat-hub duplicado 8 7        # el 8 queda duplicado del 7
uv run aeat-hub duplicado 8 --quitar # deshacer: vuelve a pendiente
```

En la ficha del dashboard hay el botón **Marcar duplicado de…** (y **Quitar duplicado** si ya lo es) que hace lo mismo sin salir del navegador.

### `ordenar`

Reubica en disco documentos ya ingeridos (p. ej. si estaban en `processed/` de una versión anterior).

```bash
uv run aeat-hub ordenar --actividad CI-VA-001
```

### `dashboard`

Vista habitual del libro. Escribe un HTML autocontenido (sin CDN) y, por defecto, **lo sirve en `http://127.0.0.1:8765`** para abrir la ficha de cada factura, el PDF, corregir NIF/importes y validar. SQLite es el maestro. `--no-serve` solo genera el fichero. `--no-open` no lanza el navegador.

```bash
uv run aeat-hub dashboard --actividad CI-VA-001 --year 2026
uv run aeat-hub dashboard --actividad CI-VA-001 --year 2026 --reparse --no-open --no-serve
```

Salida: `exports/dashboard_CI-VA-001_2026.html` y regenera el Excel del ejercicio. Tres pestañas: **Libro** (tabla única; pulsa la fila o el total para abrir la ficha de la factura, con volver atrás y las líneas extraídas; nº de factura al inicio y **Estado** fijo a la derecha — verde Validado / rojo Por validar; **Columnas** enseña u oculta campos; embudo por columna — el KPI *Por revisar* filtra los pendientes; fecha como rango, con botones **T1–T4** conmutables dentro del embudo de fecha; lápiz para corregir NIF/base/IVA/total; el lápiz de la cabecera personaliza expediente/titular/inmueble; Abrir documento; los duplicados quedan **ocultos por defecto** — se ven solo si se marcan en el embudo de Estado), **Duplicados** (fusionados y sospechosos con su gemelo enlazado, fuera de los totales) e **Insights** (KPIs, frase, gasto de los doce meses, por emisor e IVA soportado por tipo; el rango de fechas —libre, con presets guardados o T1–T4— filtra KPIs, gráficos y tabla de IVA, mientras la Renta usa siempre el ejercicio completo; los avisos enlazan facturas sin fecha y conflictos de agrupación). **Exportar visible** descarga un CSV de las filas que pasan el filtro. El xlsx completo sigue disponible al lado, en Libro, con la hoja `Trimestres` (cortes T1–T4: gastos, ingresos, mejoras, neto e IVA soportado).

`--reparse` actualiza emisor/fecha/importes desde el OCR ya guardado **salvo asientos validados** (también refresca la factura canónica y las líneas de la tabla, respetando campos que el usuario ya corrigió). Luego genera el HTML.

### `export`

Excel opcional para quien lo necesite (gestor, hoja de cálculo). El maestro sigue siendo SQLite.

```bash
uv run aeat-hub export --actividad CI-VA-001 --year 2026 --xlsx
uv run aeat-hub export --actividad CI-VA-001 --year 2026 --reparse
```

Escribe `exports/libro_CI-VA-001_2026.xlsx`. Hojas: `Gastos`, `Ingresos`, `Mejoras`, `Duplicados`, `Reclasificar`, `Resumen_rubro`, `Resumen_inmueble`, `Casillas_IRPF` (borrador de totales para el anexo de inmueble de la Renta; **no** presenta el modelo 100). Los duplicados **no** entran en los resúmenes ni en las casillas.

### `reparse`

```bash
uv run aeat-hub reparse --actividad CI-VA-001
```

Igual que `--reparse` de `dashboard`/`export`, pero no genera ficheros.

### `ocr-status`

Lista los motores y **qué haría `auto` en esta máquina**. No requiere `--data-dir`.

### Dual Vision + RapidOCR (`dual`)

Auditoría, no ingest. Corre **los dos** motores sobre las mismas facturas, compara campos fiscales y escribe un Excel. SQLite no cambia.

```bash
uv run aeat-hub dual
uv run aeat-hub dual --path ~/factura.jpg
uv run aeat-hub dual --inbox
```

Salida: `exports/dual_vision_rapid.xlsx` (hojas `Como_usarlo`, `Resumen`, `Campos`, `Discrepancias`, `Textos_OCR`).

Flujo: ingest (`auto`) → SQLite; dual → Excel de confianza; si hay conflicto en NIF/número/fecha/total, revisas el asiento; el libro se mira con `dashboard`.

### `eval`

Bake-off contra un set de oro. Detalle en [evals.md](evals.md).

```bash
uv run aeat-hub eval
uv run aeat-hub eval --engines native,rapid,vision
uv run aeat-hub eval --no-synthetic
```

Informe JSON en `<data-dir>/evals/eval-*.json`. Las facturas reales no salen del data-dir.

## Variables de entorno

Ver [`.env.example`](../.env.example).

| Variable | Uso |
| --- | --- |
| `AEAT_HUB_DATA_DIR` | Raíz de datos |
| `AEAT_HUB_UNLIMITED_OCR_URL` | POST OpenAI-compatible |
| `AEAT_HUB_UNLIMITED_OCR_GGUF` | Ruta al GGUF |
| `AEAT_HUB_UNLIMITED_OCR_MMPROJ` | Proyector visión (llama-mtmd-cli) |
| `AEAT_HUB_PADDLEOCR_VL` | `1` / `true` / `yes` / `on` para intentar Paddle |
| `AEAT_HUB_OLLAMA_URL` | Base de Ollama (default `http://127.0.0.1:11434`) |
| `AEAT_HUB_OLLAMA_OCR_MODEL` | Modelo Ollama (default `deepseek-ocr`) |

No copies un `.env` con rutas personales al repositorio público.
