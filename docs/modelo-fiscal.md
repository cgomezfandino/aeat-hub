# Modelo fiscal

AEAT Hub no sustituye a un gestor ni presenta modelos. Codifica el criterio para **no mezclar** libros y para **no meter una mejora como gasto del año**.

## Dos regímenes (no mezclar)

| Código CLI | Régimen | Uso típico | IVA en el MVP |
| --- | --- | --- | --- |
| `capital_inmobiliario` | Rendimientos de capital inmobiliario (LIRPF arts. 22–24) | Alquiler de vivienda (Valladolid) | El alquiler de vivienda habitual suele estar **exento** de IVA. Se guarda el IVA de facturas de proveedores si aparece. |
| `actividad_economica` | Actividad económica (estimación directa, etc.) | Autónomo / negocio | Rubros iniciales de ingresos, gastos e inversión. Libro IVA / modelo 303 **no** implementado aún. |

El mismo titular puede tener **varios expedientes**. El ingest siempre lleva `--actividad`.

Un alquiler es actividad económica solo en supuestos tasados (local afecto + empleado a jornada completa, art. 27.2 LIRPF). El expediente semilla `CI-VA-001` es **capital inmobiliario**.

## Expediente semilla

Al hacer `aeat-hub init`:

- Titular (NIF marcador `00000000T` si no pasas `--nif`).
- Actividad `CI-VA-001` · «Alquiler Valladolid» · `capital_inmobiliario`.
- Inmueble «Vivienda Valladolid» (municipio Valladolid, 100 % titularidad, uso vivienda).

La referencia catastral no se rellena en la semilla a propósito (dato personal).

## Plan de cuentas — capital inmobiliario

### Ingresos

| Nombre | Casilla Renta | Carpeta en archivo |
| --- | --- | --- |
| Alquiler | `ingresos` | `ingreso/renta` |
| Indemnización | `ingresos` | `ingreso/indemn` |

### Gastos del ejercicio (art. 23 LIRPF: conservación, no mejora)

Solo son deducibles los suministros **si los paga el arrendador** (no el inquilino).

| Nombre | Casilla Renta | Carpeta |
| --- | --- | --- |
| Luz | `suministros` | `gasto/luz` |
| Agua | `suministros` | `gasto/agua` |
| Internet | `suministros` | `gasto/internet` |
| Comunidad | `comunidad` | `gasto/comunidad` |
| Seguro | `seguros` | `gasto/seguro` |
| IBI | `ibi` | `gasto/ibi` |
| Hogar | `otros` | `gasto/hogar` |
| Reparación | `reparacion` | `gasto/reparacion` |
| Intereses | `intereses` | `gasto/interes` |
| Administración | `admin` | `gasto/administracion` |

### Inversión (se capitaliza; no es gasto del año)

| Nombre | Casilla Renta | Carpeta |
| --- | --- | --- |
| Ventanas | `mejoras` | `mejora/pvc` |
| Suelo | `mejoras` | `mejora/solado` |
| Revestimientos | `mejoras` | `mejora/revest` |
| Mano de obra | `mejoras` | `mejora/mano-de-obra` |
| Otras mejoras | `mejoras` | `mejora/otras-mejoras` |
| Amortización | `amortizacion` | `amortizacion/amortizacion` |

El cálculo automático de amortización **no** está en el MVP: la cuenta existe para cuando se asiente a mano o en una fase posterior.

## Mejora vs reparación

- **Reparación / conservación:** mantener el inmueble (fontanería, desatasco, avería de caldera). Gasto del ejercicio.
- **Mejora:** aumenta el valor o la vida útil (ventanas PVC, solado nuevo, revestimiento). Se suma al valor de adquisición y se amortiza.

Si el texto es solo «mano de obra» sin contexto de PVC/solado/revestimiento, el asiento queda **pendiente**. Eso es deliberado.

## Plan de cuentas — actividad económica (stubs)

| Tipo | Nombre |
| --- | --- |
| Ingreso | Ingresos de explotación |
| Gasto | Compras y servicios |
| Gasto | Suministros de la actividad |
| Gasto | Seguridad social del autónomo |
| Inversión | Bienes de inversión |

Tipos de IVA previstos a futuro: 21 / 10 / 4 / 0 / exento. Hoy se extraen de la factura si el parser los ve; no hay liquidación 303.

Cada negocio propio (p. ej. una aplicación web) es **otro expediente**
`actividad_economica`, no el de Valladolid. Hasta que exista el libro IVA,
ese expediente solo sirve para no mezclar facturas; no genera un 303.

## Qué computa (una sola regla)

`fiscal/computo.py`: computa lo **validado por una persona** que no es
duplicado ni rechazado. Se aplica a KPIs, insights, libro, trimestres, IRPF y
Excel. La confianza del clasificador (estado `confirmado` automático) no basta:
acierta el rubro, no garantiza que los importes leídos sean los del documento.
Lo no validado se muestra siempre aparte («Pendiente de revisar: N · X €») y
va a la hoja Excel *Por revisar*.

## Campos legales de la factura

`Asiento` guarda los campos de los art. 6, 7 y 15 RD 1619/2012 que antes solo
vivían en el JSON de la extracción: dirección (recibida/emitida respecto al
titular), tipo (completa/simplificada/rectificativa; `sin_determinar` si el
documento no lo dice), receptor y su NIF, retención IRPF, recargo de
equivalencia, factura rectificada y su enlace, moneda y mención legal. El
desglose por tipo va en `asiento_iva`.

Una rectificativa se enlaza con la factura que rectifica (en ambos sentidos),
pero no excluye nada: si sustituye a la original (p. ej. factura completa en
lugar del ticket) hay que rechazar la original; si es por diferencias, se suman.

El NIF del titular decide la dirección y, más adelante, si el IVA es deducible
(art. 97 LIVA: factura a nombre del titular). Con el NIF de ejemplo
`00000000T` no se puede comprobar.

## Cortes (año y trimestre)

- **Alquiler (capital inmobiliario):** lo que va a Hacienda es **anual**
  (Renta). `dashboard` y `export` cortan por `--year`. Un trimestre es una
  vista sobre ese año, no un modelo distinto.
- **Actividad económica:** el 303, el 130, el 111, el 115 y el 349 son
  **trimestrales**; el 347 y el resumen del IVA (base del 390) son anuales.
  `aeat-hub modelo <n> --actividad … --year … [--trimestre …]`.

## Perfil fiscal de la actividad

`aeat-hub actividad perfil` (`fiscal/perfil.py`) fija:

- **Régimen de IRPF:** estimación directa normal, estimación directa simplificada, estimación objetiva o capital inmobiliario.
- **Régimen de IVA:** general, recargo de equivalencia, simplificado, exento, criterio de caja o REAGYP.
- **Datos de la actividad:** territorio, epígrafe IAE, fecha de alta, % de la vivienda afecto y rendimiento neto del año anterior (minoración del 130).
- **NIF real del titular.** Cambiarlo recalcula emitidas y recibidas.

Lo no rellenado toma un valor por defecto, se marca como tal y los borradores lo avisan. El alquiler de un inmueble que no es vivienda no es exento de IVA.

## Parámetros por ejercicio

`fiscal/normativa/eAAAA.py` guarda, con su fuente, lo que cambia de un año a otro:

- tipos de IVA y de recargo, y casillas del 303;
- umbral de bien de inversión y presunción del 50 % para vehículos;
- pago fraccionado del 20 % y minoración del 130;
- provisiones y gastos de difícil justificación (5 %, máximo 2.000 €);
- suministros de la vivienda (30 %) y límites de manutención;
- umbral del 347 y tipos de retención.

2024, 2025 y 2026 están verificados contra la sede de la AEAT. Un ejercicio sin módulo usa el anterior y todos sus borradores dicen «parámetros no verificados». **Cada año hay que añadir su módulo.**

## Deducibilidad factura a factura

`fiscal/deducibilidad.py` da por separado el IVA deducible y el gasto en IRPF, con la regla y la cita de cada decisión. El IVA no deducido de un gasto afecto es mayor gasto.

| Caso | IVA | IRPF | Norma |
|---|---|---|---|
| Factura completa a nombre del titular | 100 % | base | — |
| Simplificada sin NIF del destinatario | 0 % | base + IVA | art. 97 LIVA, art. 7.2 RD 1619/2012 |
| A nombre de otro NIF | 0 % | base + IVA | art. 97 LIVA |
| Vehículo | 50 % presunto | 0 (salvo afectación exclusiva) | art. 95.Tres LIVA, art. 22.2 RIRPF |
| Suministros de la vivienda | % afecto | 30 % × % afecto | art. 30.2.5ª LIRPF |
| Manutención | hasta el límite | hasta 26,67 €/día en España sin pernocta | art. 9 RIRPF, art. 96 LIVA |
| Exento, recargo, capital inmobiliario | 0 % | base + IVA (+ recargo) | art. 94 y 154 LIVA |
| Bien de inversión | 100 % | 0 (se amortiza) | art. 28 LIRPF |
| Presupuesto/albarán, moneda extranjera, sin clasificar | 0 | 0 | — |

La afectación fijada a mano en un asiento anula la regla de la cuenta, pero nunca un bloqueo legal (no factura, moneda, destinatario, módulos).

## Libros registro y borradores

- **Libros registro** (`aeat-hub libros`, Orden HAC/773/2019):
  - ventas e ingresos, compras y gastos y bienes de inversión;
  - en las recibidas, número de recepción e importe que computa en IRPF;
  - las rectificativas, separadas.
- **303:** IVA devengado por tipo y recargo, entregas intracomunitarias, ISP, modificaciones, autoliquidación de adquisiciones intracomunitarias, deducible (corriente, inversión por encima de 3.005,06 € o intracomunitario) y resultado 46. No compensa cuotas de periodos anteriores: lo avisa.
- **130:** casillas 01-19, con:
  - pagos de trimestres anteriores y retenciones;
  - en simplificada, provisiones y gastos de difícil justificación;
  - minoración de la casilla 13 y negativos a compensar.

  Aún sin amortizaciones.
- **111 / 115:**
  - retenciones a profesionales (07-09) y por alquiler de local (01-03);
  - solo con actividad económica (art. 76 RIRPF).
- **347:**
  - por NIF y clave A/B, más de 3.005,06 € con IVA, con desglose por trimestre;
  - excluye lo que ya va al 190/180 (con retención) o al 349, las cotizaciones y los tributos.
- **349:** NIF-IVA UE con claves A/E (bienes) o I/S (servicios).
- **Resumen anual del IVA:**
  - suma de los cuatro 303 con la numeración del 303;
  - el 390 tiene casillas propias.

Cada casilla guarda sus asientos (`--detalle`). Nada se presenta: son borradores para revisar.

## Capital inmobiliario: art. 23 LIRPF

`aeat-hub actividad inmueble` guarda los datos del inmueble:

- valor catastral y de la construcción;
- coste de adquisición y mejoras anteriores;
- días arrendado;
- reducción (50/60/70/90);
- excesos pendientes de años anteriores.

Con ellos el borrador de la Renta aplica:

- **Límite de intereses + reparación y conservación:** no pueden superar los ingresos. El pequeño mantenimiento también entra en el límite. Se aplican primero los excesos de hasta 4 años y el sobrante se arrastra.
- **Amortización:** 3 % sobre el mayor de coste o valor catastral, sin suelo, más las mejoras.
- **Reducción por alquiler de vivienda:** solo sobre rendimiento positivo.
- **Cotitularidad.**

## Borrador para la Renta (capital inmobiliario)

Hacienda **no** recibe el Excel de facturas. En el modelo 100 se informan **totales** del inmueble. El dashboard y la hoja `Casillas_IRPF` agrupan el libro así:

| Concepto en la Renta | Cuentas del libro | ¿Resta del año? |
| --- | --- | --- |
| Ingresos íntegros | Alquiler, Indemnización | — |
| Intereses y financiación | Intereses | Sí |
| Conservación y reparación | Reparación | Sí |
| IBI y tasas | IBI | Sí |
| Comunidad | Comunidad | Sí |
| Seguros | Seguro | Sí |
| Suministros (si los paga el arrendador) | Luz, Agua, Internet | Sí |
| Administración / defensa | Administración | Sí |
| Otros necesarios | Hogar | Sí (revisa que no sea mejora) |
| Amortización | Amortización | Sí |
| Mejoras | Ventanas, Suelo, Revestimientos, Mano de obra, Otras mejoras | **No** (se capitalizan) |

Esto es un **criterio de trabajo**, no un envío a la AEAT ni un dictamen.

## Lista de cuentas en el CLI

```bash
uv run aeat-hub cuentas --regimen capital_inmobiliario
uv run aeat-hub cuentas --regimen actividad_economica
```
