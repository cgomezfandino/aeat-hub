# Handoff — modelo OCR Gemini 2.5 Flash (04 oct 2026)

Sesión de decisión. No hubo cambio de código ni de esquema. El modelo por defecto ya era `gemini-2.5-flash` y se queda.

## Decisión

El extractor de facturas difíciles sigue siendo **Gemini 2.5 Flash** (`gemini-2.5-flash`).

- `src/aeat_hub/ocr/gemini.py` tiene `DEFAULT_MODEL = "gemini-2.5-flash"`.
- `AEAT_HUB_GEMINI_MODEL` sigue comentada en `.env`. No hace falta definirla.
- La cascada local (PDF nativo y, en foto o escaneo, Apple Vision) sigue como camino sin nube.
- DeepSeek-OCR por Ollama sigue opcional (`--ocr deepseek`). No entra en el ingest por defecto.
- Flash Lite (`gemini-2.5-flash-lite`) se probó y no se adopta.

`docs/ocr.md` deja de citar `gemini-1.5-flash` como ejemplo de override.

## Clave de Google

Se rotó `GEMINI_API_KEY` por seguridad. La clave nueva es una auth key de AI Studio (prefijo `AQ.`). Una llamada mínima a `gemini-2.5-flash` devolvió HTTP 200, tanto con la cabecera `x-goog-api-key` como con el `?key=` que ya usa el proveedor. La clave no está en git (`.env` está en `.gitignore`).

## Medición

Mismo set de oro: dos Leroy reales (`leroy-foto-20260918`, `leroy-rectificativa-20260905`) y la factura sintética Iberdrola en PDF y PNG. El oro real vive en el data-dir, fuera de git. Gemini no está en `aeat-hub eval`; estas pasadas puntuaron el JSON con las mismas reglas de NIF, número, fecha e importes. No se guardó el JSON de las facturas.

Tarifa de pago estándar en la página de Google del 1 oct 2026: Flash $0,30 / $2,50 por millón de tokens de entrada y salida; Flash Lite $0,10 / $0,40. La salida incluye los tokens de razonamiento.

| Motor | Foto | Rectificativa | Sintéticos | Notas |
| --- | --- | --- | --- | --- |
| Gemini 2.5 Flash, pasada emparejada del 4 oct | 6/7 y luego 7/7 | 7/7 y 7/7 | 7/7 y 7/7 | Único fallo: NIF del receptor vacío en la primera pasada de la foto. Importes bien en las seis llamadas. |
| Gemini 2.5 Flash-Lite, misma pasada | 3/7 y 3/7 | 6/7 y 6/7 | 6/7 y 6/7 | NIF del receptor vacío en las seis, también en el sintético. En la foto, base, IVA y total no coincidieron en ninguna pasada. |
| Apple Vision, 20 sep | 4/7, texto OCR 7/7 | 4/7, texto OCR 7/7 | 7/7 | El parser pierde número, base y cuota. Mediana ~0,9 s. |
| DeepSeek-OCR local, 20 sep | 0/7 | 0/7 | 7/7 y 7/7 | La foto salió como tabla HTML enorme. |

La imagen entra igual en los dos Gemini: 1.266 tokens. Flash añade entre 759 y 5.825 tokens de razonamiento; Lite no añade ninguno. Una foto sale a unos $0,011–$0,012 con Flash y a $0,0004 con Lite. Las seis llamadas de la muestra salieron a unos $0,062 frente a $0,002. Lite responde en 2–3 s; Flash tarda 20–28 s en los documentos reales.

## Qué no se tocó

- Código, tests y esquema. No se relanzó pytest.
- No hay push. `develop` sigue por delante de `origin/develop`.

## Siguiente bloque

1. Ingerir el resto del alquiler de Valladolid (luz, agua, internet, comunidad, seguros, rentas) y validar el lote de bricolaje. No mezclarlo con gastos de las webs.
2. Revisar el NIF de emisor al validar: a veces se guarda el del titular.
3. Poder corregir el número de factura en la ficha HTML. Hoy solo existe `aeat-hub factura numero`.
4. Confirmar el Split View de `/asiento/<id>` en Safari.
5. Más adelante: libro de actividad económica y borrador 303, amortización, y ampliar el set de oro. Meter `gemini` en `aeat-hub eval` si se quiere repetir esta medición sin un script aparte.
