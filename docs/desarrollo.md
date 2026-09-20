# Desarrollo

## Entorno

```bash
git clone https://github.com/cgomezfandino/aeat-hub.git
cd aeat-hub
uv sync --group dev
uv run pytest
```

Python 3.12 (`.python-version`). Dependencias en `pyproject.toml` + `uv.lock`.

Extra HEIC: `uv sync --extra heic`.

## Convenciones

- Español en CLI, README y docs. Identificadores de código en español de dominio (`asiento`, `actividad`) cuando es el lenguaje del problema; el resto en inglés técnico habitual (`ingest`, `layout`).
- No commitear facturas, SQLite, Excel, HTML de exports, `.env`, modelos `.gguf`/`.onnx`.
- Los tests no deben llamar a GPU ni descargar Unlimited-OCR. El OCR de imagen se inyecta (`FakeRapid`) o se usa PDF con texto. El bake-off real (`aeat-hub eval` con RapidOCR/Vision) no corre en pytest.
- Si el sistema no está seguro entre reparación y mejora, el asiento queda `pendiente`.

## Añadir una cuenta

1. `AccountDef` en `src/aeat_hub/fiscal/accounts.py`.
2. Si el slug de carpeta no debe ser el último segmento del código, añádelo en `SLUG_OVERRIDE` (`filing.py`).
3. Si hay proveedores típicos, una tupla en `KEYWORD_ACCOUNTS` (`classify.py`).
4. Test sintético.
5. `init` en un data-dir ya creado **no** borra cuentas; `seed_cuentas` inserta las que falten. En un libro viejo, vuelve a ejecutar `aeat-hub init` (no recrea `CI-VA-001` si existe) o inserta a mano.

## Añadir un proveedor OCR

Implementa `available() -> tuple[bool, str]` y `transcribe(path) -> OCRResult`. Si no puede, lanza `ProviderUnavailable`. Enchúfalo en `ocr/cascade.py` (`OPTIONAL` o en la cascada `auto`). Documenta env vars en `.env.example` y `docs/ocr.md`. Añade un test de fallback.

## Data-dir de desarrollo

Usa un tmp o un subdirectorio, no el libro real:

```bash
uv run aeat-hub init --data-dir /tmp/aeat-hub-dev
```

El libro personal está en `/Volumes/SSDCX9/data/aeat-hub`.

## Publicar

Repo: [https://github.com/cgomezfandino/aeat-hub](https://github.com/cgomezfandino/aeat-hub) (público, MIT).

Antes de un commit: `uv run pytest` y `git status` sin PDFs ni `ledger.sqlite`.
