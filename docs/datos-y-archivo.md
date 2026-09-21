# Datos y archivo en disco

El código vive en el git. **Los datos fiscales no.**

## Dónde

Por defecto: `/Volumes/SSDCX9/data/aeat-hub`

Override: `--data-dir` o `AEAT_HUB_DATA_DIR`.

Ese árbol está en `.gitignore` (`*.pdf`, `*.sqlite`, `*.xlsx`, `inbox/`, `data/`, etc.). El repo público no debe contener un solo NIF real.

## Árbol

```
$AEAT_HUB_DATA_DIR/
  inbox/                 # bandeja de entrada (el usuario suelta aquí)
    DEJAR_AQUI.txt
  archivo/               # biblioteca ordenada
    CI-VA-001/
      2026/
        03/
          gasto/luz/
          gasto/agua/
          ingreso/renta/
          mejora/pvc/
          duplicado/luz/
          pendiente/sin-cuenta/
      sin_fecha/
        00/
          pendiente/sin-cuenta/
  processed/             # legado; el ingest actual ya no deja aquí el destino final
  rejected/
    hash/                # mismo binario (SHA-256)
    error/               # un fichero petó; el lote sigue
  logs/
    ingest-AAAAMMDD-HHMMSS.log
  db/
    ledger.sqlite        # fuente de verdad
  exports/
    dashboard_CI-VA-001_2026.html
    libro_CI-VA-001_2026.xlsx
  models/                # sitio previsto para pesos OCR locales
  config.json
```

Nombre de fichero archivado: `{sha256[:12]}_{nombre_original}` para no pisar dos facturas con el mismo nombre.

## Inbox

Extensiones aceptadas: PDF y fotos (JPG, PNG, WEBP, TIFF, HEIC). `DEJAR_AQUI.txt` se ignora.

Hoy el inbox es **plano** (no recorre subcarpetas). Deja los ficheros en la raíz de `inbox/`.

## Reglas de carpeta destino

Definidas en `aeat_hub.filing`:

| Situación | `año` | `mes` | tipo | rubro |
| --- | --- | --- | --- | --- |
| Factura con fecha y cuenta | año de la factura | `01`–`12` | `gasto` / `ingreso` / `mejora` / `amortizacion` | slug de la cuenta |
| Sin fecha | `sin_fecha` | `00` | según tipo | slug o `sin-cuenta` |
| Pendiente sin cuenta | según fecha | | `pendiente` | `sin-cuenta` |
| Duplicado fiscal/sospechoso | según fecha | | `duplicado` | slug si hay cuenta |

Slugs de carpeta: a partir del nombre o del id interno (`Luz` → `luz`), con excepciones (`Mano de obra` → `mano-de-obra`). El usuario no escribe esos ids; son detalle de archivo.

Una factura **pendiente con cuenta propuesta** (p. ej. PVC a confianza 0,72) **sí** se archiva bajo `mejora/pvc`, para que Finder ya esté ordenado. Sigue saliendo en `aeat-hub pendientes`.

## Movimientos

| Acción | Inbox | Original fuera del inbox (`--path`) |
| --- | --- | --- |
| Ingest | **Mueve** a `archivo/...` | **Copia** a `archivo/...` (no borra el original) |
| Mismo SHA-256 | Mueve a `rejected/hash/` | Copia a `rejected/hash/` |
| `reclasificar` | Mueve dentro de `archivo/` al nuevo rubro y borra carpetas vacías | |
| `ordenar` | Reubica según el asiento actual | |

`ruta_almacenada` en la tabla `documentos` apunta siempre al sitio actual.

## Dashboard y Excel

La vista habitual es `exports/dashboard_CI-VA-001_2026.html` (`aeat-hub dashboard`). El Excel es opcional. Ninguno de los dos es el maestro: un segundo comando lo regenera desde SQLite. Si reclasificas, vuelve a generar el ejercicio.
