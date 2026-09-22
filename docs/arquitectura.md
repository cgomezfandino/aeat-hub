# Arquitectura

AEAT Hub es un **backend local** (CLI Python) para llevar libros auxiliares de ingresos y gastos. No hay cuenta en la nube ni presentación telemática de modelos. El dashboard se sirve en `127.0.0.1` para abrir documentos y corregir asientos; no escucha fuera de la máquina.

## Principios

1. **Todo en local.** Facturas, NIF y SQLite no salen de la máquina.
2. **SQLite es el maestro.** El dashboard HTML (y el Excel, si lo pides) son vistas: las correcciones del navegador pasan por `127.0.0.1` y se escriben en SQLite.
3. **Un expediente, un régimen.** El CLI exige `--actividad` para no mezclar alquiler y autónomo.
4. **Si duda, no inventa.** Reparación vs mejora y documentos sin cuenta quedan `pendiente`.
5. **El fichero sigue a la clasificación.** Tras el ingest (y tras reclasificar) el PDF/foto se mueve a `archivo/año/mes/tipo/rubro`.

## Piezas

```
inbox  →  OCR  →  parser factura ES  →  ER (emisor+nº)  →  clasificador  →  SQLite
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
| ER | `aeat_hub.er` | Raw + factura canónica + relaciones |
| Duplicados | `aeat_hub.dedupe` | SHA-256 y sospechosos si no hay ID |
| Clasificación | `aeat_hub.classify` | Palabras clave + reglas aprendidas |
| Archivo | `aeat_hub.filing` | Árbol año/mes/tipo/rubro |
| Ingest | `aeat_hub.ingest` | Orquesta el lote del inbox |
| Dashboard | `aeat_hub.dashboard` | HTML local del ejercicio |
| Servidor local | `aeat_hub.hub_http` | `127.0.0.1`: HTML, ficha `/asiento/<id>`, `/doc/<id>`, correcciones |
| Excel | `aeat_hub.export` | XLSX opcional por ejercicio |

## Flujo de un documento

```mermaid
flowchart TD
  drop[Usuario deja PDF o foto en inbox]
  hash[SHA-256]
  dup1{Ya existe el fichero?}
  ocr[OCR: nativo o RapidOCR]
  parse[Parser factura ES]
  er{Mismo emisor y número?}
  class[Clasificar cuenta]
  sqlite[Raw + factura + asiento]
  file[Mover a archivo/año/mes/tipo/rubro]
  reject[rejected/hash]
  attach[Evidencia extra, mismo asiento]

  drop --> hash --> dup1
  dup1 -->|sí nivel 1| reject
  dup1 -->|no| ocr --> parse --> er
  er -->|sí, total coherente| attach --> file
  er -->|no| class --> sqlite --> file
```

## Dominio

- **Titular:** persona física o jurídica (NIF).
- **Actividad / expediente:** `capital_inmobiliario` o `actividad_economica`. Aquí se separa la “razón social / actividad” de cara a Hacienda.
- **Inmueble:** solo capital inmobiliario (p. ej. vivienda en Valladolid).
- **Documento:** el fichero raw (hash, OCR, ruta en disco).
- **Factura:** entidad canónica (emisor + número). Varios documentos pueden ser evidencia de una.
- **Asiento:** el apunte contable/fiscal (un asiento por factura).
- **Proyecto de mejora:** agrupará PVC + materiales + mano de obra (tabla lista; el CLI de proyectos aún no está).
- **Regla aprendida:** `(actividad, NIF emisor) → cuenta` tras un `reclasificar`.

## Hardware de diseño

MacBook Pro **M1 Pro, 16 GB, sin NVIDIA**. Por eso el OCR pesado (Unlimited-OCR oficial CUDA) no es el motor por defecto. Detalle en [ocr.md](ocr.md).
