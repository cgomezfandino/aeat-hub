# Referencia de código

Paquete: `src/aeat_hub/`. Python ≥ 3.12. Entrada CLI: `aeat_hub.cli:app`.

## Módulos

| Ruta | Qué hace |
| --- | --- |
| `__init__.py` | `__version__` (`0.1.0`) |
| `cli.py` | Comandos Typer |
| `paths.py` | `DataLayout`, default `/Volumes/SSDCX9/data/aeat-hub` |
| `db.py` | Engine SQLite, `PRAGMA foreign_keys=ON`, sesiones |
| `models.py` | ORM |
| `seed.py` | Cuentas + `CI-VA-001` |
| `services.py` | `initialize`, `alta_actividad`, lookups |
| `fiscal/nif.py` | NIF/NIE/CIF (dígito de control) |
| `fiscal/money.py` | `1.234,56` → `Decimal` |
| `fiscal/accounts.py` | Plan de cuentas |
| `fiscal/irpf.py` | Mapeo a conceptos de Renta (capital inmobiliario) |
| `extract/schema.py` | `InvoiceExtract` (Pydantic) |
| `extract/parser.py` | Heurísticas sobre texto |
| `ocr/cascade.py` | Orquestación |
| `ocr/pdf_native.py` | Texto PDF |
| `ocr/rapid.py` | RapidOCR + numpy |
| `ocr/render.py` | PDF/foto → PIL (HEIC opcional) |
| `ocr/unlimited.py` | HTTP o `llama-mtmd-cli` |
| `ocr/paddle_vl.py` | PaddleOCR-VL si el flag está on |
| `ocr/apple_vision.py` | Vision.framework (opcional, macOS) |
| `ocr/dual.py` | Consenso Vision vs RapidOCR |
| `export_dual.py` | Excel de auditoría dual |
| `ocr/tesseract.py` | Tesseract CLI (opcional) |
| `ocr/base.py` | `OCRResult`, `ProviderUnavailable` |
| `evals/` | Bake-off: oro, métricas, runner |
| `extract/ids.py` | `numero_norm` / `emisor_norm` |
| `er.py` | Clustering factura canónica y relaciones |
| `media.py` | SHA-256 y average hash |
| `dedupe.py` | Tres niveles |
| `classify.py` | Reglas + `reclassify` / `validar_asiento` / `reabrir_asiento` |
| `filing.py` | Árbol en disco |
| `ingest.py` | Pipeline del inbox |
| `dashboard.py` | HTML local del ejercicio |
| `hub_http.py` | Servidor `127.0.0.1` (libro, ficha `/asiento/<id>`, docs, correcciones) |
| `edits.py` | NIF/importes/validar/reabrir y líneas de factura |
| `export.py` | OpenPyXL (opcional) |

## Tablas SQLite (`db/ledger.sqlite`)

| Tabla | Clave | Notas |
| --- | --- | --- |
| `titulares` | `id` | `nif` único |
| `actividades` | `id` | `codigo` único (`CI-VA-001`) |
| `inmuebles` | `id` | FK actividad |
| `cuentas` | `codigo` PK | tipo + régimen |
| `proyectos_mejora` | `id` | Preparado; sin CLI aún |
| `documentos` | `id` | Raw: `sha256` único, OCR, ruta, `paginas` |
| `extracciones` | `id` | Lo que el parser vio en un ingest (no se pisa) |
| `facturas` | `id` | Entidad canónica (NIF/emisor + `numero_norm`) |
| `relaciones` | `id` | ER: `evidencia`, `continuacion`, `conflicto`, … |
| `asientos` | `id` | FK actividad/inmueble/documento/`factura`/cuenta |
| `cambios` | `id` | Log humano: campo, antes, después |
| `reglas_aprendidas` | `id` | Único `(actividad, nif_emisor, patron)` |

### Campos relevantes de `asientos`

`tipo`, `cuenta_codigo`, `fecha`, `ejercicio`, `emisor`, `nif_emisor`, `numero_factura`, `descripcion`, `base`, `iva_tipo`, `iva_cuota`, `total`, `estado`, `confianza_clasificacion`, `origen_clasificacion`, `duplicado_de_id`, `duplicado_nivel`, `factura_id`.

## Tests (`tests/`)

Facturas sintéticas en `tests/samples.py` (CIF de juguete `B12345674`, DNI `12345678Z`). No descargan Unlimited-OCR.

| Fichero | Cubre |
| --- | --- |
| `test_nif.py` | DNI/NIE/CIF |
| `test_parser.py` | Importes y factura luz/PVC |
| `test_seed.py` | Semilla Valladolid |
| `test_classify.py` | Luz, PVC, mano de obra, aprendizaje |
| `test_dedupe.py` | Niveles 2 y 3 |
| `test_ingest.py` | PDF nativo, asiento luz, SHA |
| `test_filing.py` | Árbol año/mes/tipo/rubro y reclasificar |
| `test_export.py` | Hojas XLSX |
| `test_dashboard.py` | KPIs HTML, pendientes e IRPF |
| `test_edits.py` | Corrección NIF/importes, reapertura, líneas, confirmación y log |
| `test_irpf.py` | Casillas de Renta |
| `test_cli.py` | `init`, listar, alta AE |
| `test_ocr_optional.py` | Fallback si Unlimited no está |
| `test_dual.py` | Consenso de campos y Excel dual |
| `test_er.py` | Clustering emisor+ID, continuación, conflicto, backfill |

```bash
uv run pytest
```
