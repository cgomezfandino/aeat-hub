# Tab Insights (antes Resumen)

Fecha: 2026-09-21
Estado: aprobado en chat, pendiente de implementación

## Objetivo

La segunda pestaña del dashboard deja de llamarse **Resumen** y pasa a **Insights**. Responde dos preguntas, en este orden:

1. Cómo va el ejercicio (gastos, ingresos, evolución, alertas).
2. Cómo iría en la Renta (borrador de casillas, no presentación telemática).

El Libro no cambia de rol: sigue siendo la tabla de trabajo. Insights es la vista de lectura y de salto al Libro ya filtrado.

## Layout

Una sola columna de bloques apilados, a ancho del contenedor. No hay sub-pestañas ni columnas lado a lado entre Operativo y Renta: los gráficos y la tabla de casillas necesitan el ancho, y en móvil ya se apilan.

```
Cabecera (sin cambios de contenido)
  título, titular, franja «por revisar · sin validar · neto»
  tabs: Libro | Insights

Insights
  lead de una línea
  KPIs (Gastos, Ingresos, Mejoras, Neto, Por revisar)

  Operativo
    Evolución — Por mes | Por rubro
    Destacados — tarjetas
    Atención — alertas clicables

  Renta
    título «Como iría en la Renta»
    4 mini-KPIs
    tabla de casillas
```

En escritorio, «Por mes» y «Por rubro» siguen en dos columnas. Destacados y Atención van debajo, Destacados en rejilla y Atención en lista. En móvil, todo a una columna.

## Qué se ve

| Superficie | Texto |
| --- | --- |
| Pestaña | Insights |
| Lead | Una frase: arriba el ejercicio, abajo el borrador de la Renta. |
| Sección 1 | Operativo |
| Sección 2 | Renta. Subtítulo: borrador para copiar a la declaración; Hacienda no recibe este HTML. |

La franja de la cabecera se mantiene. Los KPIs del tab no la sustituyen: la franja es el estado del libro; los KPIs son atajos que filtran el Libro.

`data-panel` pasa de `resumen` a `insights`. IDs de pestaña y panel se renombran en consecuencia (`tab-insights`, `panel-insights`). El ancla del Libro (`#ledger`) no cambia.

## Comportamiento

Los KPIs siguen abriendo el Libro con el filtro que ya tienen (gasto, ingreso, mejora, todos, pendiente).

Alertas de Atención, si existen, son botones:

| Alerta | Efecto |
| --- | --- |
| Baja confianza | Libro + filtro Confianza = Revisar |
| Duplicados | Libro + filtro Estado = Duplicados |
| Sin rentas en el ejercicio | Libro + filtro Estado = Ingresos |

Las tarjetas de Destacados (mayor gasto, mix, validados, mejoras capitalizadas) no filtran. Son lectura.

La lógica de importes, casillas IRPF y duplicados excluidos de los totales no cambia.

## Gráficos

Siguen siendo SVG inline, sin CDN.

- Por mes: el nombre del mes se ve siempre. Si el SVG no cabe en el ancho, la figura hace scroll horizontal.
- Por rubro: la etiqueta larga se recorta; el nombre completo queda en `title`.
- Leyenda compacta, mismo código de color (gasto, ingreso, mejora).

## Fuera de alcance

- Sub-navegación dentro de Insights.
- Gráfico de acumulado anual.
- Que «Mayor gasto» o el mix filtren el Libro.
- Nuevos totales fiscales (IVA trimestral, modelo 303).
- Cambiar el cálculo de `summarize_irpf` o las cuentas.
- Rediseñar el Libro, la ficha de factura o el pie.

## Archivos

| Archivo | Cambio |
| --- | --- |
| `src/aeat_hub/dashboard.py` | HTML, CSS y JS del tab |
| `tests/test_dashboard.py` | Nombre Insights, bloques, filtros de alerta |
| `docs/cli.md` | Pestañas Libro e Insights |

## Prueba

- El HTML del ejercicio contiene el botón Insights y no el botón Resumen como pestaña.
- Existen las secciones Operativo y Renta.
- Una alerta de baja confianza, si hay asientos en ese estado, lleva `data-filter` (o equivalente) que deja el Libro en Confianza = Revisar.
- Los tests de KPIs, duplicados e IRPF existentes siguen pasando.
