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

## Esquema y migraciones (Alembic)

- El esquema vive en `src/aeat_hub/migrations/versions/`. `db.create_schema` deja
  cualquier base en `head` al arrancar; no hay `create_all`.
- `0001` es el esquema congelado a 14 oct 2026 (`migrations/baseline_0001.sql`).
  Una base anterior a Alembic pasa por los ALTER históricos (`_migrate_legacy`,
  congelado), se sella en `0001` y sigue migrando.
- Cambiar un modelo exige una revisión nueva. `tests/test_migraciones.py`
  compara migraciones y modelos y falla ante cualquier diferencia.
- En SQLite las FK se desactivan solo durante la migración (las tablas se
  recrean) y se comprueba `PRAGMA foreign_key_check` antes de confirmar.
- Importes, tipos y cantidades usan `aeat_hub.types.Fixed`: enteros escalados
  en SQLite (céntimos), `NUMERIC` en Postgres. Nunca `Numeric` a pelo ni `float`.
- Antes de migrar una base real: copia `db/ledger.sqlite*` y prueba en la copia.

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

## Ramas y entornos

Dos ramas largas, comparables en todo momento:

| Rama | Entorno | Qué entra |
| --- | --- | --- |
| `develop` | Integración (trabajo diario) | Features fusionadas por PR |
| `main` | Producción (libro publicado) | Solo PR desde `develop` cuando el lote está estable |

Flujo:

1. Parte de `develop` actualizado: `git checkout develop && git pull`.
2. Crea una rama corta: `git checkout -b feature/nombre-claro`.
3. Abre un **PR a `develop`**. El CI (`pytest`) debe pasar.
4. Cuando `develop` esté listo para publicar: **PR `develop` → `main`**. Eso es el corte productivo.

No commits directos a `main`. No PRs de una feature a `main`. Comparar entornos:

```bash
git fetch origin
git log --oneline origin/main..origin/develop   # lo que aún no es producción
```

En GitHub: `https://github.com/cgomezfandino/aeat-hub/compare/main...develop`

## Publicar

Repo: [https://github.com/cgomezfandino/aeat-hub](https://github.com/cgomezfandino/aeat-hub) (público, MIT). Rama por defecto: `develop`.

Antes de un commit: `uv run pytest` y `git status` sin PDFs ni `ledger.sqlite`.
