# Hoja de ruta

Qué cubre el MVP (v0.1.0), qué no, y el siguiente bloque de trabajo.

## Qué sí hay hoy

Libro local de **un titular**, varios expedientes. El maestro es **SQLite**
(`$AEAT_HUB_DATA_DIR/db/ledger.sqlite`). El dashboard se sirve en `127.0.0.1`
para abrir el documento, corregir NIF/importes y validar. El Excel es una
exportación opcional.

| Superficie | Sirve para | No sirve para |
| --- | --- | --- |
| Dashboard HTML | Ver el ejercicio, filtrar, abrir la ficha de cada factura (líneas compradas), editar con lápiz (confirmación + log), validar o devolver a revisión, exportar el recorte filtrado | Crear cuentas, reclasificar el rubro, presentar modelos |
| CLI | Ingest, pendientes, `validar`, `reabrir`, `reclasificar` (por nombre), `cuenta alta`, `factura numero` | Interfaz de revisión continua |
| Excel | Libro por rubro + hoja `Casillas_IRPF` (totales anuales del inmueble) | Presentar el modelo 100 / 303; cortes trimestrales |

El primer expediente semilla es el alquiler de Valladolid (`CI-VA-001`,
capital inmobiliario). Los rubros se leen y se escriben por **nombre corto**
(`Hogar`, `Luz`). Los ids internos no salen en UI, CLI ni Excel.

## Fuera de alcance ahora

- Servidor local o app que escriba SQLite desde el navegador.
- Multi-usuario, cuentas, SaaS.
- Presentación telemática (modelos 100, 130, 303, 390, 347).
- Unlimited-OCR como motor por defecto.
- APIs cloud de facturas (Azure Document Intelligence, FacturaHub, etc.).
- Cálculo automático de amortización del inmueble y de mejoras.
- CLI de proyectos de mejora (la tabla `proyectos_mejora` existe vacía de flujo).
- Libro IVA completo y liquidación 303 (tipos 21/10/4/0/exento por casilla AEAT).
- Inbox recursivo (subcarpetas).
- Watcher automático (hay que lanzar `ingest` a mano).
- Edición del Excel como maestro bidireccional.

## Cortes: año frente a trimestre

No se mezclan calendarios ni expedientes.

| Régimen | Corte que pide Hacienda | Qué hay ahora | Cómo lo haríamos |
| --- | --- | --- | --- |
| Capital inmobiliario (alquiler) | **Anual** (Renta, anexo del inmueble) | Dashboard y Excel por `--year` | El trimestre es una **vista** (jul–sep) sobre el mismo libro anual, no un modelo |
| Actividad económica (autónomo / webs) | **303 trimestral** (o mensual) + IRPF/130 más anual | Stubs de cuentas; no hay libro IVA ni borrador 303 | Un expediente por negocio; dashboard/Excel con selector T1–T4 para el 303 y vista anual para el IRPF |

Hasta que exista el libro AE, no uses `CI-VA-001` para facturas de las
aplicaciones web.

## Varios negocios

El mismo titular puede tener varios expedientes. El ingest siempre lleva
`--actividad`.

1. Alquiler Valladolid — `CI-VA-001` · `capital_inmobiliario` (ya existe).
2. Cada aplicación web — `aeat-hub actividad alta --nombre "…" --regimen actividad_economica` (el catálogo AE es stub; el 303 no está).

No mezclar gastos del piso con ads, dominio o Stripe de una web.

## Siguiente bloque natural

1. Ingerir el lote real de septiembre del alquiler (luz, agua, internet,
   comunidad, seguros, hogar, rentas) y ajustar palabras clave.
2. Corregir a mano un número de factura mal leído: `aeat-hub factura numero` (hecho en CLI). La edición en el HTML sigue pendiente.
3. Revisión que **grabe** en SQLite (servidor local mínimo: validar y
   cambiar rubro desde el HTML, sin copiar el CLI).
4. Cortes T1–T4 como filtro de dashboard/Excel sobre el libro anual.
5. Libro de actividad económica para las dos webs + borrador 303 (totales,
   sin envío).
6. Amortización y proyectos de mejora.
7. Ampliar el set de oro de `aeat-hub eval` (hoy: 2 tickets Leroy + sintético).

## Aviso

La normativa de IRPF/IVA cambia. Las cuentas y textos de este repo son un
**criterio de trabajo**, no un dictamen. Revisa cada asiento antes de declarar.
