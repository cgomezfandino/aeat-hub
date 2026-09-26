# Handoff — pulido UI del dashboard (26 sep 2026)

Estado del trabajo de interfaz del dashboard HTML tras la sesión del 26 sep.
Todo vive en un solo módulo generador: `src/aeat_hub/dashboard.py`.

## Corte de git

| Campo | Valor |
| --- | --- |
| Rama | `develop` |
| Commit | `61dde97` — `feat(dashboard): unificar hojas modales, tablas inteligentes y pulido de la ficha` |
| Push | **Pendiente** (`develop` va 1 commit por delante de `origin/develop`) |
| Tests | `uv run pytest tests/test_dashboard.py` — 17 OK |

```bash
git push   # cuando toque publicar
```

## Qué se hizo

### 1. Hojas modales unificadas (`app-sheet`)

Todos los diálogos importantes comparten el patrón visual:

- `sheet-eyebrow` — etiqueta superior
- `sheet-lead` — texto explicativo
- `sheet-foot` — pie con botones alineados (`ghost`, `export-btn`, `sheet-link`)

Diálogos migrados:

| Id | Variante | Uso |
| --- | --- | --- |
| `ficha-line-dialog` | `sheet-form` | Editar línea de factura (sustituye edición en fila) |
| `ficha-dup-dialog` | `sheet-form` | Marcar / quitar duplicado en ficha |
| `app-confirm` | `sheet-decision` | Confirmaciones genéricas |
| `app-decision` | `sheet-decision` | Decisiones del kanban de revisión |
| `rechazo-dialog` | `sheet-form` | Rechazo con motivo |
| `dup-gestor` | `sheet-compare` | Comparar y fusionar duplicados |
| `ficha-log-dialog` | `sheet-form` | Historial de cambios en ficha |
| `mast-dialog` | (ya existía) | Título del expediente |

La edición de líneas en ficha ya **no** es inline: un clic en el lápiz abre
`ficha-line-dialog`; guardar recalcula base/IVA/total; eliminar pasa por paso
de confirmación dentro del mismo sheet.

### 2. Tablas inteligentes (`smart-table`)

Helper Python `_smart_config()` + JS `_SMART_TABLE_JS` (registro global
`window.smartTableRefresh`).

Tablas con filtro y ordenación:

| Tabla | Clase | Panel |
| --- | --- | --- |
| Libro | (ya tenía) | Libro |
| Duplicados | `dup-tabla smart-table` | Duplicados |
| Revisión pendiente | `dup-tabla smart-table` | Revisión |
| IVA por tipo | `iva-tabla smart-table` | Insights |
| IRPF casillas | `irpf-table smart-table` | Insights |

Atributos de fila: `_smart_row_attrs()` embebe `data-smart-*` para filtrar sin
re-render del servidor.

### 3. Carrusel de KPIs

- Helper `_kpi_carousel()` + JS `_KPI_CAROUSEL_JS`
- Usado en masthead (`#mast-kpis`) e Insights (`#insight-kpis`)
- Scroll horizontal con snap, arrastre ratón/táctil, puntos `··_··`

### 4. Scrollbars de tablas

En `:is(.table-wrap, .review-table-wrap, .edit-lines-wrap, .libro-kpis)`:

- Ocultas por defecto
- Visibles y sutiles en `:hover`
- `.table-wrap` sin padding lateral (el `thead` oscuro llega al borde)

### 5. Cabecera oscura del libro

Pseudo-elementos en `thead th.col-sticky:first-child` (`::before` / `::after`)
para cerrar el hueco blanco a la izquierda y esquinas redondeadas.

### 6. Tabla de líneas en ficha (`/asiento/{id}`)

Problema reportado en Safari/Mac: hueco blanco entre TOTAL y ACCIONES.

Causa: la columna Acciones heredaba estilos del libro (`col-estado`: ancho
fijo + `position: sticky; right: 0`) y los anchos en `rem` con `width: auto`
en Concepto no repartían bien en WebKit.

Arreglo aplicado (verificar en Mac del usuario):

```css
.table-wrap.ficha-lines > .ficha-ledger {
  width: 100% !important;
  min-width: 0 !important;
  table-layout: fixed;
}
/* columnas en % que suman 100% */
/* sin sticky en ficha (col-sticky, col-estado, line-actions) */
```

Overrides también en media queries `@media (max-width: 1100px)` y `@media (max-width: 720px)` para que el libro no fuerce `1180px` en la ficha.

## Cómo probar

```bash
uv run aeat-hub dashboard --actividad CI-VA-001 --year 2026 --port 8765
```

Rutas clave:

| URL | Qué mirar |
| --- | --- |
| `/` | KPIs carrusel, libro con filtros, pop-ups sheet |
| `/asiento/3` | Tabla de líneas sin hueco; editar línea en sheet |
| Panel Duplicados | Tabla smart con filtros |
| Panel Revisión | Kanban + tabla smart |
| Insights | KPIs carrusel, tablas IVA/IRPF smart |

Recarga dura tras cambios CSS: **Cmd+Shift+R**.

## Archivos tocados

| Archivo | Cambio |
| --- | --- |
| `src/aeat_hub/dashboard.py` | HTML, CSS, JS del dashboard (~+1800 líneas netas) |
| `tests/test_dashboard.py` | Aserciones `smart-table`, `dup-tabla`, ids de sheet |

No hay migraciones SQLite ni cambios de API HTTP en este pase.

## Pendiente / verificar

1. **Tabla ficha en Safari (Mac)** — arreglo aplicado pero no confirmado por
   el usuario tras el commit. Si persiste el hueco, probar:
   - quitar `col-estado` del `<th>` de Acciones en `_lineas_thead()`
   - `table-layout: auto` solo en ficha
   - inspeccionar en DevTools si alguna regla de `.ledger-table` gana por orden

2. **Push a `origin/develop`** — commit local sin publicar.

3. **PR a `main`** — no toca hasta estabilizar el lote en `develop`.

4. Temas de hoja de ruta sin relación con este pase (siguen abiertos):
   - Número de factura editable en HTML (solo CLI hoy)
   - Revisar NIF de emisor al validar
   - Libro actividad económica + borrador 303

## Convenciones para el siguiente agente

- El dashboard es **un solo archivo Python** que emite HTML estático + JS
  inline. No hay bundler ni CSS externo (salvo Google Fonts en `_FONT_LINKS`).
- Nuevos diálogos: usar `app-sheet` + `sheet-foot`, no `edit-dialog` ni
  `edit-actions`.
- Nuevas tablas con filtro: añadir `smart-table`, `data-smart-config` y
  `data-smart-*` en filas vía `_smart_row_attrs()`.
- Estilos de ficha: prefijo `.ficha-ledger` / `.table-wrap.ficha-lines` para
  no heredar sticky/ancho del libro.
- Tests: `tests/test_dashboard.py` comprueba presencia de ids y clases clave;
  ampliar si se añaden diálogos o tablas nuevas.
- No commitear sin pedido explícito del usuario (regla del repo).

## Referencias

- Hoja de ruta general: `docs/hoja-de-ruta.md`
- Revisión pipeline anterior: `docs/revision-modelo-pipeline-2026-09.md`
- Transcript de la sesión (Cursor): chat `b5dbf2a7-67b9-4a8f-be01-84ba201647f8`
