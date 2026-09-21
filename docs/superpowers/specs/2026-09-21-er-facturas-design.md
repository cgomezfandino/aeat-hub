# Entity resolution de facturas (raw + relaciones)

Fecha: 2026-09-21
Estado: hecho

## Objetivo

Cada fichero se guarda como **raw**. El parser extrae el número de factura. Varios documentos del mismo emisor + mismo ID se agrupan en una **factura canónica** y un solo asiento. Así no se cuenta dos veces un ticket paginado o escaneado dos veces.

No es software oficial de la AEAT. Esta entrega no escribe desde el HTML ni deja corregir el número a mano (siguiente PR).

## Fuera de alcance

- `aeat-hub factura numero` ni edición en el navegador.
- Partir un PDF que mezcle dos ventas distintas.
- Unir ficheros físicamente en un solo PDF.
- Sustituir los duplicados nivel 2–3 cuando no hay ID.

## Capas

| Capa | Tabla | Qué es |
| --- | --- | --- |
| Raw | `documentos` | Fichero inmutable (SHA, OCR, ruta). Un PDF de varias páginas = un raw. |
| Observación | `extracciones` | Lo que el parser vio en ese ingest (`numero_raw` / `numero_norm`, NIF, importes, `Pag. x/y` de ticket). No se pisa. |
| Entidad | `facturas` | Canónica por expediente: NIF (o emisor normalizado) + `numero_norm`. |
| Vínculos | `relaciones` | `evidencia`, `continuacion`, `misma_factura`, `duplicado_fichero`, `conflicto`. |
| Libro | `asientos` | Un asiento por factura (`factura_id`). `documento_id` = evidencia principal para el archivo en disco. |

## Clustering

1. Siempre se guarda el raw (salvo el mismo SHA-256 → `rejected/hash/`).
2. Si hay `numero_norm` y coincide NIF o emisor:
   - Total coherente (±0,02 €) o uno de los dos sin total → misma factura, relación `evidencia` (o `continuacion` si `Pag.` > 1). **No** hay segundo asiento. Si el nuevo raw trae total y el canónico no, se enriquece.
   - Totales distintos → dos facturas, ambas `estado_er=conflicto`, relación `conflicto`.
3. Sin ID: se crea factura+asiento y siguen los duplicados actuales de `dedupe.py`.

Paginación de ticket: `Pag. 1 / 2`. El sello Adobe `1 / 3` no cuenta.

IDs: `número de factura`, Leroy `064-0009-…`, ticket Obramat `010-…-NFS: …`.

## Corrección humana

El modelo deja `numero_raw` y `numero_norm` en la extracción. Un comando o la UI para cambiar el canónico y re-clusterizar es el siguiente PR.
