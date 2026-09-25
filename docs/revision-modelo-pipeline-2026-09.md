# Revisión del modelo y del pipeline (24 sep 2026)

Repaso completo del modelo de datos, del pipeline de carga/procesado de
facturas y del dashboard, con lo corregido en este pase y lo que queda
apuntado. Referencias de línea al código de la fecha de la revisión.

## Veredicto corto

El diseño de fondo es sólido: SQLite como maestro, capa raw
(`Documento`/`Extraccion`) separada de la canónica (`Factura`) y del libro
(`Asiento`), auditoría de correcciones (`Cambio`) y archivo en disco guiado
por el asiento. Los fallos encontrados no eran de diseño sino de **fronteras
entre capas**: regenerar el libro dentro de la transacción de una corrección,
mover ficheros antes del commit, y dos capas (factura/asiento) que duplican
campos sin sincronizador completo.

## Fallos críticos corregidos (P0)

1. **Corrección humana perdida si fallaba la regeneración del libro.**
   `write_dashboard` (que escribe el XLSX en disco) corría dentro de la
   transacción del `POST /api/asientos/{id}`: un XLSX abierto en Excel
   (`PermissionError`) hacía rollback y el usuario perdía la corrección sin
   saberlo. Además, un `ValueError` (fecha inválida) o `RuntimeError` (rubro
   desconocido) escapaba como 500 sin cuerpo JSON.
   *Arreglado:* commit explícito antes de regenerar; la regeneración es
   best-effort (si falla, la respuesta incluye `"libro": "no regenerado (…)"`);
   `ValueError`/`RuntimeError` devuelven 400 con el mensaje en español.
   Test: `tests/test_hub_http.py`.

2. **Fichero huérfano en `archivo/` tras un fallo del lote.** Si el commit
   fallaba (p. ej. `database is locked` con el servidor levantado) después de
   que «archivar» moviera el fichero, el rollback deshacía las filas pero el
   fichero quedaba en `archivo/` sin `Documento`: factura invisible para
   siempre. De paso, el ítem de éxito ya añadido quedaba con un `asiento_id`
   que apuntaba a filas deshechas.
   *Arreglado:* el lote pasa un `probe` con el SHA; si el fichero ya no está
   en inbox, se busca bajo `archivo/` por `{sha12}_*` y se rescata a
   `rejected/error/`. El ítem solo cuenta como éxito cuando el commit
   persiste. Test: `tests/test_ingest.py`.

3. **Facturas sin fecha invisibles en todos los ejercicios.** Un asiento sin
   `fecha` queda con `ejercicio=None` y tanto el dashboard como el Excel
   filtran por `ejercicio == año`: no aparecía en ningún año ni en la cola de
   revisión, y jamás se corregía.
   *Arreglado:* Insights avisa («N sin fecha, fuera de todo ejercicio») con
   enlaces a las fichas.

4. **`reparse_asientos` estaba roto en silencio.** Usaba
   `Classification.confidence`, que no existe (es `confianza`): cualquier
   reparse que llegara a reclasificar lanzaba `AttributeError`. Nunca se vio
   porque el único test existente validaba antes y saltaba el asiento.
   *Arreglado y testeado.*

## Consistencia corregida (P1)

- **Sync Factura↔Asiento al editar.** Parchear solo `base` recalculaba
  `iva_tipo` del asiento pero no lo copiaba a la factura. Ahora `iva_tipo`
  viaja siempre que el payload toque `base` o `iva_cuota`.
- **Drift del reparse.** El reparse reescribía el asiento y dejaba la factura
  con importes caducados → falsos conflictos/merges en entity resolution
  posteriores. Ahora sincroniza la factura, **salvo** campos donde asiento y
  factura ya divergían (señal de corrección humana). El número de factura no
  se toca: la identidad la gestiona `aeat-hub factura numero`.
- **SQLite concurrente.** WAL + `busy_timeout=5000` en el engine para que el
  CLI y el servidor local convivan sin `database is locked`.
- **Normalización unificada.** `dedupe` truncaba el emisor a 48 y ER a 80
  (dos nociones de «mismo emisor»), y re-implementaba `normalize_numero`.
  Ahora todo pasa por `extract/ids.py`.
- **Detallitos:** `Asiento.numero_factura` String(80)→String(120) (alineado
  con `Factura`/`Extraccion`); inmueble del asiento determinista
  (`order_by(Inmueble.id)`).

## Dashboard: qué mejoró

El rango de fechas de Insights solo repintaba los dos gráficos y la frase;
los KPIs y la Renta quedaban con el año completo. Ahora:

- **KPIs coherentes**: Gastos/Ingresos/Mejoras/Neto siguen el rango (y
  vuelven al año completo con «Año completo»). «Por revisar» sigue siendo del
  año: es una cola, no una métrica de periodo. La Renta se etiqueta
  explícitamente «ejercicio completo».
- **Trimestres T1–T4** como presets con nombre (siguiente paso que faltaba de
  la hoja de ruta), junto a los rangos guardados por el usuario.
- **Tabla «IVA soportado»** por tipo (21/10/4/0/otros/sin tipo) con base,
  cuota y total de gastos y mejoras — base del futuro borrador 303.
- **Avisos ampliados**: conflictos de entity resolution («mismo número, total
  distinto») y facturas sin fecha, con enlaces.

En la segunda tanda del mismo día, los trimestres llegaron también al resto
del libro: botones T1–T4 en el filtro de fecha del Libro (conmutable) y hoja
`Trimestres` en el Excel (gastos/ingresos/mejoras/neto/IVA soportado por
trimestre + total del año).

Validado en navegador: T1 fija el rango, un rango vacío pone KPIs a 0,00 y la
tabla IVA muestra «Sin IVA registrado en este rango», «Año completo» restaura
todo.

## Hallazgos del modelo que quedan apuntados (no corregidos)

Por orden de interés, con su porqué:

1. **Las líneas de desglose no tienen tabla.** *Resuelto el mismo día, en la
   segunda tanda:* hoy existe la tabla `lineas` como fuente de verdad editable
   por asiento; `Documento.json_extraido` queda como salida intacta del
   modelo y `Extraccion` sigue siendo el histórico. La migración de los JSON
   históricos corre en `create_schema`.
2. **Sin restricciones aritméticas.** *Abordado el 25 sep:* las tolerancias
   viven ahora en `fiscal/cuadres.py` (una sola fuente: 0,02 cabecera /
   0,05 líneas) y tanto el ingest como el nuevo `aeat-hub doctor` avisan
   cuando base+IVA no cuadra con el total o el IVA no es 21/10/4/0. Sigue
   sin haber CONSTRAINT en la base de datos (decisión: SQLite + libro
   editable a mano).
3. **Tres nociones de duplicado** que se solapan: SHA de fichero, niveles 1–3
   del asiento (`duplicado_de_id`/`duplicado_nivel`) y conflicto ER. La fusión
   ER marca `duplicado_nivel=2` mezclando conceptos.
4. **Dedupe asimétrico con número.** *Resuelto el mismo día, en la tercera
   tanda:* con número parseado, los niveles 3 (NIF+importe±3 días,
   emisor+importe±3 días, phash) ya no se ignoran — marcan el asiento como
   **sospechoso** (`pendiente` + `duplicado_nivel=3` + `duplicado_de_id`) en
   vez de saltárselos. Lo destapó un duplicado real de IKEA (factura
   `ESCINV…` y servicio `ESSIM…`, misma fecha e importe, números distintos)
   que el pipeline dejó pasar. Sin número, el nivel 3 sigue marcando
   `duplicado` directamente. Compras legítimas repetidas quedan en la cola de
   revisión, no fuera de los totales.
5. **`Relacion` sin FK ni cascadas.** *Mitigado el 25 sep:* `aeat-hub
   doctor` audita las relaciones polimórficas (huérfanas), ficheros
   perdidos y cuadres. Las FKs siguen sin existir (la polimorfía las
   complica); no hay borrado aún.
6. **`ProyectoMejora` es vaporware**: tabla y FK sin relationship ni uso.
7. **Confianza mezclada.** `Documento.confianza` guarda la puntuación del
   parser (presencia de campos), no la del OCR; la confianza del motor se
   descarta y el umbral «baja» 0,80 mezcla ambas cosas con la del clasificador.
8. **`totals_compatible(None, x) = True`**: un documento con el mismo número y
   sin total se adhiere como evidencia sin aviso ni recompute.
9. **Multi-titular a medias**: `alta_actividad` siempre toma el primer
   `Titular`; el NIF semilla es un marcador.
10. **Fechas del `Cambio` en UTC** (`CURRENT_TIMESTAMP` de SQLite) formateadas
    como si fueran locales: el historial desfasa 1–2 h en España.
11. **Migraciones ad-hoc en cada arranque** (`_migrate` + `_backfill_er` en
    cada comando): sin versionado (Alembic) y con escrituras ocultas en
    lecturas.
12. **Doble implementación de gráficos/frase** en Python y JS que ya driftan
    sutilmente (`casefold` vs `toLocaleLowerCase("es")`, mensajes distintos
    con rango vacío). El JSON embebido invita a dejar el servidor como
    fallback `<noscript>`.

## Pipeline: puntos vigilar (no corregidos)

- `_peek_amount` puede cruzar un salto de página y robar el total siguiente.
- `IVA_RATE_RE` se queda con el primer «IVA x %» del texto.
- Modelo de IVA único por cabecera: las facturas con 4 % + 21 % guardan un
  solo triple (las líneas sí tienen tipo).
- `AMOUNT_RE` exige 2 decimales: «3.500» o «12,5» no casan.
- Subprocesos de OCR sin `encoding="utf-8"` explícito (locale-dependiente).
- Auto-«confirmado» por presencia de campos (confianza ≥ 0,8), no por
  exactitud.
- `place_file` puede sobrescribir silenciosamente si el destino con sufijo
  también existe.
- Regenerar HTML+XLSX en cada edición de ficha: correcto tras este pase, pero
  sigue siendo caro (posible export perezoso).

## Tests

126 pasando (112 previos + 14 nuevos): servidor 400/best-effort, rescate de
huérfanos (unidad e integración), sync factura↔asiento al parchear y al
reparsear, normalización única de emisor, presencia en el HTML de KPIs con
id, tabla IVA, T1–T4 (Insights y filtro del Libro) y avisos (sin fecha y
conflicto ER); tabla `lineas` (edición sin pisar el JSON, edición sin
documento, migración desde JSON histórico, refresco con reparse) y hoja
`Trimestres` del Excel.
