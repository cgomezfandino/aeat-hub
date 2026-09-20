# Modelo fiscal

AEAT Hub no sustituye a un gestor ni presenta modelos. Codifica el criterio para **no mezclar** libros y para **no meter una mejora como gasto del año**.

## Dos regímenes (no mezclar)

| Código CLI | Régimen | Uso típico | IVA en el MVP |
| --- | --- | --- | --- |
| `capital_inmobiliario` | Rendimientos de capital inmobiliario (LIRPF arts. 22–24) | Alquiler de vivienda (Valladolid) | El alquiler de vivienda habitual suele estar **exento** de IVA. Se guarda el IVA de facturas de proveedores si aparece. |
| `actividad_economica` | Actividad económica (estimación directa, etc.) | Autónomo / negocio | Cuentas stub `AE.*`. Libro IVA / modelo 303 **no** implementado aún. |

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

| Código | Nombre |
| --- | --- |
| `AE.ING.VENTAS` | Ingresos de explotación |
| `AE.GAS.COMPRAS` | Compras y servicios |
| `AE.GAS.SUMINISTROS` | Suministros de la actividad |
| `AE.GAS.SS` | Seguridad social del autónomo |
| `AE.INV.BIENES` | Bienes de inversión |

Tipos de IVA previstos a futuro: 21 / 10 / 4 / 0 / exento. Hoy se extraen de la factura si el parser los ve; no hay liquidación 303.

## Borrador para la Renta (capital inmobiliario)

Hacienda **no** recibe el Excel de facturas. En el modelo 100 se informan **totales** del inmueble. El dashboard y la hoja `Casillas_IRPF` agrupan el libro así:

| Concepto en la Renta | Cuentas del libro | ¿Resta del año? |
| --- | --- | --- |
| Ingresos íntegros | `CI.ING.RENTA`, `CI.ING.INDEMN` | — |
| Intereses y financiación | `CI.GAS.INTERES` | Sí |
| Conservación y reparación | `CI.GAS.REPARACION` | Sí |
| IBI y tasas | `CI.GAS.IBI` | Sí |
| Comunidad | `CI.GAS.COMUNIDAD` | Sí |
| Seguros | `CI.GAS.SEGURO` | Sí |
| Suministros (si los paga el arrendador) | `CI.GAS.LUZ`, `AGUA`, `INTERNET` | Sí |
| Administración / defensa | `CI.GAS.ADMIN` | Sí |
| Otros necesarios | `CI.GAS.HOGAR` | Sí (revisa que no sea mejora) |
| Amortización | `CI.AMO.INMUEBLE` | Sí |
| Mejoras | `CI.MEJ.*` | **No** (se capitalizan) |

Esto es un **criterio de trabajo**, no un envío a la AEAT ni un dictamen.

## Lista de cuentas en el CLI

```bash
uv run aeat-hub cuentas --regimen capital_inmobiliario
uv run aeat-hub cuentas --regimen actividad_economica
```
