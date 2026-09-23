# Insights: el año y después la Renta

Fecha: 2026-09-22
Estado: implementado

Sustituye, en `2026-09-21-insights-tab-design.md`, los gráficos, Destacados y las alertas que abrían el Libro. El renombre Resumen → Insights y el bloque Renta siguen vigentes. Los KPIs y las alertas ya no filtran el Libro.

## Objetivo

La pestaña Insights se lee de arriba abajo y no navega.

1. Cómo va el año: una frase, el gasto mes a mes y quién lo cobró.
2. Cómo iría en la Renta: el borrador que ya existe.

## Orden

```
KPIs (Gastos, Ingresos, Mejoras, Neto, Por revisar)
Línea de aviso, solo si hay algo que decir
Frase
Gasto por mes | Por emisor
Renta (sin cambios)
```

El título Operativo sigue encima de la frase y de los gráficos. En escritorio los dos gráficos van en dos columnas. En móvil, uno bajo el otro. La Renta ocupa el ancho, debajo. El mes de la frase se escribe completo («agosto»); el eje del gráfico usa la abreviatura de tres letras.

Se quitan Destacados, Atención como lista de botones y el gráfico por rubro.

## Cifras y avisos

Los cinco KPIs siguen siendo cifras, no botones.

La línea de aviso, bajo los KPIs, junta en una sola frase lo que aplique:

- asientos por revisar
- ejercicio sin ingresos
- duplicados fuera de los totales

Si no hay nada de eso, la línea no se pinta. No lleva `data-filter` ni cambia de pestaña.

## Frase

El denominador es el gasto del ejercicio: asientos de tipo gasto, sin duplicados y sin mejoras.

1. Si el emisor con más gasto supone al menos el 50 %, la frase es suya: «{Emisor} concentra el {pct} % del gasto ({importe}).»
2. Si no, y un mes supone al menos el 40 %: «El gasto se concentra en {mes}: {importe}, el {pct} % del año.»
3. Si no: «Hasta {último mes con gasto} van {importe} en gasto.»

`{pct}` es un entero. `{importe}` usa el mismo formato de euro que el resto del dashboard. El nombre es el `emisor` guardado, recortado a 32 caracteres con puntos suspensivos si hace falta; el nombre completo va en `title`. No se inventa un alias. Dos textos iguales salvo espacios y mayúsculas cuentan como el mismo emisor. Un emisor vacío se muestra como «Sin emisor».

## Gráficos

SVG inline, sin CDN. Sin leyenda que haya que descifrar: el importe va en la propia barra cuando no es cero.

**Gasto por mes.** Doce meses, de enero a diciembre, también los que van a cero. Solo barras de gasto. Si en el ejercicio hay algún ingreso, ese mes lleva una segunda barra en verde, con su importe. Las mejoras no entran.

**Por emisor.** Barras horizontales de mayor a menor, con importe y porcentaje del gasto. Como mucho seis emisores; el resto se suma en una barra «Resto». Solo gasto. El mismo criterio de nombre que la frase.

## Renta y pie

El bloque Renta no cambia: cuatro cifras, tabla de casillas y sus filtros de columna. Esos filtros no salen de Insights.

Exportar visible y el libro completo siguen solo en la pestaña Libro.

## Fuera de alcance

- Gráfico de acumulado.
- Volver a pintar el rubro en Insights.
- Atajos desde la frase o las barras hacia el Libro.
- Cambiar `summarize_irpf`, las cuentas o el Libro.
- Alias comerciales distintos del nombre guardado.

## Archivos

| Archivo | Cambio |
| --- | --- |
| `src/aeat_hub/dashboard.py` | Frase, gráfico de doce meses, gráfico por emisor; fuera Destacados, Por rubro y alertas clicables |
| `tests/test_dashboard.py` | Frase, doce meses, emisor, ausencia de Por rubro y de `data-filter` en alertas; Renta sigue |
| `docs/cli.md` | La frase de Insights deja de decir que las alertas filtran el Libro |

## Prueba

- Con un ejercicio en el que un emisor lleva al menos la mitad del gasto, el HTML contiene la frase de concentración y el porcentaje.
- El gráfico mensual incluye enero y diciembre aunque su gasto sea cero.
- El gráfico de emisor lista el mayor primero y, si hay más de seis, una fila Resto.
- No aparece el título Por rubro ni la sección Destacados.
- Las alertas no son botones y no tienen `data-filter`.
- Siguen el título Operativo, la sección Renta y el botón Exportar visible dentro del panel Libro.
