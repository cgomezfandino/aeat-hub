# Hoja de ruta

Qué cubre el MVP (v0.1.0), qué no, y el siguiente bloque de trabajo.

## Qué sí hay hoy

Libro local de **un titular**, varios expedientes. El maestro es **SQLite**
(`$AEAT_HUB_DATA_DIR/db/ledger.sqlite`). El dashboard se sirve en `127.0.0.1`
para abrir el documento, corregir NIF/importes y validar. El Excel es una
exportación opcional.

| Superficie | Sirve para | No sirve para |
| --- | --- | --- |
| Dashboard HTML | Ver el ejercicio (Libro e Insights), filtrar y ordenar, abrir la ficha, editar cabecera y líneas (confirmación + log), borrado recuperable, validar, exportar el recorte | Crear cuentas, presentar modelos |
| CLI | Ingest, pendientes, `validar`, `reabrir`, `reclasificar` (por nombre), `cuenta alta`, `factura numero` | Interfaz de revisión continua |
| Excel | Libro por rubro, hoja `Trimestres` (cortes T1–T4) y hoja `Casillas_IRPF` (totales anuales del inmueble) | Presentar el modelo 100 / 303 |

El primer expediente semilla es el alquiler de Valladolid (`CI-VA-001`,
capital inmobiliario). Los rubros se leen y se escriben por **nombre corto**
(`Hogar`, `Luz`). Los ids internos no salen en UI, CLI ni Excel.

## Fuera de alcance ahora

- App multi-usuario, cuentas y SaaS. El dashboard local sí escribe SQLite (validar, ficha, títulos del expediente).
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

## Dónde quedó el 23 sep 2026

Ramas: solo `develop` y `main`. El corte de Insights y del desglose OCR está
en las dos (`develop` en el merge de la PR #3, `main` en la PR #4). Un solo
directorio de trabajo, en `develop`, limpio.

El libro del alquiler vive en el data-dir local, fuera de git. El lote de
bricolaje de 2026 está reingestado y pendiente de validar. Insights lee el
año (frase, doce meses, emisor) y admite un rango de fechas; la Renta sigue
siendo el ejercicio entero. La ficha marca huecos de calidad. Si las líneas
no cuadran con el total, el ingest prueba el otro motor de imagen una vez.

El 24 sep cayó la revisión del modelo y del pipeline
(`docs/revision-modelo-pipeline-2026-09.md`): la corrección de ficha ya no se
pierde si el Excel está abierto, los ficheros huérfanos se rescatan a
`rejected/error`, las facturas sin fecha avisan en Insights, el reparse
sincroniza la factura y vuelven a funcionar (estaba roto silenciosamente).
SQLite pasa a WAL. Insights gana KPIs coherentes con el rango, trimestres
T1–T4 con nombre y tabla de IVA soportado por tipo.

Esa misma tarde: el desglose vive en su propia tabla `lineas` (el JSON del
documento queda como salida intacta del modelo; migración automática al
arrancar) y los trimestres T1–T4 llegan al filtro de fecha del Libro y al
Excel (hoja `Trimestres`).

## Siguiente bloque natural

1. Ingerir el resto del alquiler (luz, agua, internet, comunidad, seguros,
   rentas) y ajustar palabras clave. No mezclar con gastos de las webs.
2. Revisar el NIF de emisor al validar: a veces se guarda el del titular.
3. El número de factura se corrige por CLI (`aeat-hub factura numero`). En
   el HTML todavía no.
4. ~~Cortes T1–T4~~ Hechos en Insights, en el filtro del Libro y en el Excel
   (hoja `Trimestres`).
5. Libro de actividad económica para las webs + borrador 303 (totales, sin
   envío). La tabla de IVA soportado por tipo y la hoja `Trimestres` ya
   apuntan al 303.
6. Amortización y proyectos de mejora.
7. Ampliar el set de oro de `aeat-hub eval` (hoy: 2 tickets Leroy + sintético).

## Aviso

La normativa de IRPF/IVA cambia. Las cuentas y textos de este repo son un
**criterio de trabajo**, no un dictamen. Revisa cada asiento antes de declarar.
