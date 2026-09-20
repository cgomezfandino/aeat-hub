# Arquitectura

AEAT Hub es un **backend local** (CLI Python) para llevar libros auxiliares de ingresos y gastos. No hay servidor, ni cuenta en la nube, ni presentación telemática de modelos.

## Principios

1. **Todo en local.** Facturas, NIF y SQLite no salen de la máquina.
2. **SQLite es el maestro.** El dashboard HTML (y el Excel, si lo pides) son fotos, no el libro de trabajo.
3. **Un expediente, un régimen.** El CLI exige `--actividad` para no mezclar alquiler y autónomo.
4. **Si duda, no inventa.** Reparación vs mejora y documentos sin cuenta quedan `pendiente`.
5. **El fichero sigue a la clasificación.** Tras el ingest (y tras reclasificar) el PDF/foto se mueve a `archivo/año/mes/tipo/rubro`.

## Piezas

```
inbox  →  OCR  →  parser factura ES  →  duplicados  →  clasificador  →  SQLite
                                                                      ↓
                                                               archivo en disco
                                                                      ↓
                                                               dashboard HTML
                                                                      ↓
                                                          Excel opcional (export)
```

| Pieza | Módulo | Responsabilidad |
| --- | --- | --- |
| CLI | `aeat_hub.cli` | Comandos Typer |
| Rutas | `aeat_hub.paths` | `AEAT_HUB_DATA_DIR`, carpetas inbox/archivo/db |
| Persistencia | `aeat_hub.db`, `models` | SQLAlchemy + SQLite |
| Semilla | `aeat_hub.seed` | Cuentas + expediente Valladolid |
| OCR | `aeat_hub.ocr` | Cascada nativo → RapidOCR → opcionales |
| Parser | `aeat_hub.extract` | NIF, fecha, número, bases, IVA, total |
| Duplicados | `aeat_hub.dedupe` | SHA-256, clave fiscal, sospechoso/phash |
| Clasificación | `aeat_hub.classify` | Palabras clave + reglas aprendidas |
| Archivo | `aeat_hub.filing` | Árbol año/mes/tipo/rubro |
| Ingest | `aeat_hub.ingest` | Orquesta el lote del inbox |
| Dashboard | `aeat_hub.dashboard` | HTML local del ejercicio (sin servidor) |
| Excel | `aeat_hub.export` | XLSX opcional por ejercicio |

## Flujo de un documento

```mermaid
flowchart TD
  drop[Usuario deja PDF o foto en inbox]
  hash[SHA-256]
  dup1{Ya existe el fichero?}
  ocr[OCR: nativo o RapidOCR]
  parse[Parser factura ES]
  dup2{Duplicado fiscal o sospechoso?}
  class[Clasificar cuenta]
  sqlite[Insertar documento + asiento]
  file[Mover a archivo/año/mes/tipo/rubro]
  reject[rejected/hash]

  drop --> hash --> dup1
  dup1 -->|sí nivel 1| reject
  dup1 -->|no| ocr --> parse --> dup2 --> class --> sqlite --> file
```

## Dominio

- **Titular:** persona física o jurídica (NIF).
- **Actividad / expediente:** `capital_inmobiliario` o `actividad_economica`. Aquí se separa la “razón social / actividad” de cara a Hacienda.
- **Inmueble:** solo capital inmobiliario (p. ej. vivienda en Valladolid).
- **Documento:** el fichero (hash, OCR, JSON extraído, ruta en disco).
- **Asiento:** el apunte contable/fiscal (cuenta, importes, estado).
- **Proyecto de mejora:** agrupará PVC + materiales + mano de obra (tabla lista; el CLI de proyectos aún no está).
- **Regla aprendida:** `(actividad, NIF emisor) → cuenta` tras un `reclasificar`.

## Hardware de diseño

MacBook Pro **M1 Pro, 16 GB, sin NVIDIA**. Por eso el OCR pesado (Unlimited-OCR oficial CUDA) no es el motor por defecto. Detalle en [ocr.md](ocr.md).
