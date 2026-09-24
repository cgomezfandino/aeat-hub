# Clasificación y duplicados

## Estados de un asiento

| Estado | Cuándo |
| --- | --- |
| `pendiente` | Sin cuenta, o cuenta con confianza &lt; 0,8 (p. ej. una mejora). Hay que revisar. |
| `confirmado` | Cuenta asignada con confianza ≥ 0,8, o tras `reclasificar` / `validar`. |
| `validado` (flag) | Tú lo has revisado. `reparse` **no** pisa emisor, fecha, importes ni rubro. |
| `duplicado` | Misma factura fiscal o sospechoso (niveles 2–3). Se exporta; no entra en resúmenes. |
| `rechazado` | Reservado; el CLI aún no lo asigna. |

El duplicado **de fichero** (mismo SHA-256) no crea asiento: el archivo va a `rejected/hash/`.

## Origen de la clasificación

| Origen | Significado |
| --- | --- |
| `regla` | Palabra clave / proveedor conocido |
| `aprendida` | NIF emisor (o patrón) guardado al reclasificar |
| `usuario` | Este asiento lo acaba de reclasificar el usuario |
| `pendiente` | El sistema no asignó cuenta |

Prioridad: **regla aprendida (NIF) > palabras clave > heurística mejora/reparación**.

## Palabras clave (capital inmobiliario)

Coincidencias en emisor + texto OCR, en este orden:

| Pistas (minúsculas) | Rubro destino | Confianza |
| --- | --- | --- |
| iberdrola, endesa, naturgy, holaluz, curenerg, i-de redes | Luz | 0,90 |
| aquavall, aquona, aqualia, aguas de, canal de isabel | Agua | 0,90 |
| movistar, telefónica, orange, vodafone, digi, másmóvil, yoigo, pepephone, lowi | Internet | 0,88 |
| comunidad de propietarios, administrador de fincas | Comunidad | 0,92 |
| mapfre, allianz, mutua madrileña, línea directa, zurich, reale, pelayo | Seguro | 0,85 |
| ibi, tasa de basura, gerencia territorial | IBI | 0,86 |
| indemnización | Indemnización | 0,80 |
| arrendamiento, renta de alquiler | Renta | 0,80 |
| ventana, pvc, climalit, carpinter | Ventanas | 0,72 |
| tarima, parquet, solado, suelo laminado, porcelánico | Suelo | 0,72 |
| revestimiento, alicatado | Revestimientos | 0,70 |
| leroy merlin, bricomart, bauhaus | Hogar | 0,60 |

La confianza 0,72 de PVC deja el asiento **pendiente** (revisión humana) pero ya lo archiva en `mejora/pvc`.

### Mejora vs reparación (si no hubo keyword de cuenta)

- «Mano de obra» + pvc/ventana/tarima/solado/revest → rubro «Mano de obra».
- «Mano de obra» sola → pendiente, sin cuenta.
- Reparación/avería/desatasco/fontanería/caldera, sin pistas de reforma → rubro «Reparación».

En actividad económica, de momento solo se detecta «seguridad social» / «reta» → rubro «Seguridad social del autónomo».

## Aprendizaje

`aeat-hub reclasificar <id> <rubro>`:

1. Asigna la cuenta (por nombre), estado `confirmado`, origen `usuario`, flag **`validado`**.
2. Upsert de regla `(actividad_id, nif_emisor, patrón vacío) → cuenta`.
3. Por defecto aplica la misma cuenta a otros asientos **pendiente** del mismo NIF (`origen=aprendida`). `--solo-este` lo evita.
4. Mueve el fichero al nuevo rubro.

`aeat-hub validar <id>` confirma el asiento **sin cambiar el rubro**. Úsalo cuando el modelo acertó y solo quieres el check humano. `aeat-hub reabrir <id>` (o pulsar el botón verde **Validado** en el libro) lo deshace.

Las facturas futuras de ese NIF en esa actividad se clasifican solas. Los asientos `validado` no se vuelven a parsear.

## Duplicados (tres niveles)

| Nivel | Criterio | Efecto |
| --- | --- | --- |
| 1 | Mismo SHA-256 | No hay segundo asiento. Fichero a `rejected/hash/` |
| 2 | Mismo `NIF + número + fecha + total`, o `número + fecha + total` si el NIF no salió en el OCR | Asiento `duplicado`, enlace `duplicado_de_id` |
| 3 | Mismo NIF o mismo emisor + mismo total + fecha ±3 días, **o** perceptual hash de la primera página (Hamming ≤ 10) | Igual, `duplicado_nivel=3` |

El phash se calcula **antes** de insertar el documento, para no compararse consigo mismo.

Con número parseado, el nivel 3 no marca `duplicado` directamente: la misma compra puede aparecer con número de factura y de servicio (caso IKEA: `ESCINV…` frente a `ESSIM…`, misma fecha e importe). En ese caso el asiento queda **sospechoso**: `estado=pendiente` con `duplicado_nivel=3` y `duplicado_de_id` apuntando al gemelo, para revisión humana. Sin número, el nivel 3 sigue marcando `duplicado` a secas.

Los tres niveles se listan (2 y 3 en `aeat-hub duplicados`) y salen en el dashboard (filtro de tabla) y en la hoja Excel `Duplicados`. No se silencian.

## Entity resolution (factura canónica)

El duplicado de asiento es la red de seguridad **cuando no hay número**. Si el parser ve un ID (nº de factura, Leroy `064-…`, ticket Obramat `010-…-NFS:`), el ingest agrupa por **emisor/NIF + número**:

1. Cada fichero se guarda en `documentos` (raw) y deja una fila en `extracciones`.
2. Varios raw del mismo ID = **una** fila en `facturas` y **un** asiento. Relación `evidencia` o `continuacion` (`Pag. 2/2`).
3. Mismo ID y total distinto (> 0,02 €) = dos facturas, `estado_er=conflicto`.
4. Un PDF de varias páginas sigue siendo un solo raw.

El libro y el Excel cuentan asientos, no ficheros. El dashboard muestra un chip `N docs` si hay más de una evidencia.

Corregir a mano un número mal leído: `aeat-hub factura numero <asiento> <número>`. El HTML sigue sin escribir.

Para fusionar a mano un duplicado evidente sin cambiar el número: `aeat-hub duplicado <duplicado> <bueno>` (y `--quitar` para deshacer). Mueve las evidencias a la factura buena, marca nivel 2 con relación `misma_factura` de fuente `usuario`, lo anota en el historial `Cambio` y reubica el fichero. En la ficha del dashboard: botones **Marcar duplicado de…** / **Quitar duplicado**.
