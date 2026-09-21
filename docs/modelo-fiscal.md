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

## Cortes (año y trimestre)

- **Alquiler (capital inmobiliario):** lo que va a Hacienda es **anual**
  (Renta). `dashboard` y `export` cortan por `--year`. Un trimestre es una
  vista sobre ese año, no un modelo distinto.
- **Actividad económica:** el 303 es **trimestral** (o mensual). Ese corte
  aún no está. No uses el Excel de `CI-VA-001` como si fuera un 303.

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
