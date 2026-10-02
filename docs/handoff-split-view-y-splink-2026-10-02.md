# Handoff — Split View, Deduplicación Splink con SKUs y OCR Multimodal (02 oct 2026)

Estado de la plataforma tras la sesión del 2 de octubre de 2026 en la rama `develop`.

---

## 1. Corte de Git

| Campo | Valor |
| --- | --- |
| Rama | `develop` |
| Commits recientes | `848b35e` — `feat: integración de Gemini OCR, subida web drag-and-drop y mejoras de auditoría`<br>`3309e3a` — `feat: unificar modelo de confianza, deteccion de duplicados por SKU y etiquetas UI`<br>`a91060f` — `feat: incorporar comparacion de SKUs y scoring explicable con Splink en deteccion de duplicados`<br>`d02bc29` — `feat: implementar Split View responsivo en ficha de factura con visor PDF y acciones rápidas` |
| Estado del árbol | Limpio (`working tree clean`), 4 commits por delante de `origin/develop` |
| Tests | `uv run pytest` — **177/177 pasando (100 % OK en ~11 s)** |

---

## 2. Novedades y Componentes Implementados

### A. Split View Responsivo en la Ficha de Factura (`/asiento/<id>`)
Se ha transformado la vista de detalle del asiento en un entorno de trabajo con doble panel:

1. **Panel Izquierdo: Visor de Documento Embebido (`.ficha-pane-doc`)**
   - **Sticky Container:** Fijado a la altura de la pantalla (`position: sticky; top: 14px; height: calc(100vh - 28px); min-height: 600px;`), permitiendo contrastar visualmente el ticket o factura contra los datos fiscales y líneas extraídas.
   - **Visor PDF e Imágenes:**
     - Para PDFs: `<iframe>` con `#view=FitH` para autoajuste al ancho y controles nativos del navegador (zoom, paginación, búsqueda).
     - Para imágenes (JPG, PNG, WebP): Contenedor centrado sobre lienzo oscuro neutro (`#474b4e`) con fondo de tarjeta y sombreado.
   - **Barra de herramientas:**
     - Nombre original del documento con truncado inteligente.
     - Botón "Abrir documento" (en nueva pestaña).
     - Botón "Descargar".
     - Botón **"Ocultar visor"** para alternar a ancho completo cuando se revisan facturas con tablas de líneas densas (con botón de recuperación rápida y persistencia en `sessionStorage`).

2. **Panel Derecho: Datos, KPIs y Tabla de Líneas (`.ficha-pane-data`)**
   - **Validación en un Clic:** Botón principal `[ ✓ Validar asiento ]` para facturas pendientes y `[ ↺ Reabrir ]` con modal de confirmación para asientos validados.
   - **Alerta de Sospecha de Duplicado:** Banner superior en color advertencia si existen candidatos detectados por Splink, mostrando emisor, fecha, importe y desglose explicativo de pesos, con botón `[ Revisar candidato ]` para fusionar directamente.
   - **Carrusel de KPIs y Editor de Líneas:** Preserva el carrusel de métricas fiscales, la edición modal por línea, el recálculo automático de totales/IVA y la auditoría de cambios (`Cambio`).

3. **Adaptabilidad Móvil y Tablet (`≤ 1024px`)**
   - La cuadrícula se apila verticalmente.
   - Se incorpora el botón **`[ 📄 Ver documento ]`** en la barra superior para alternar la visibilidad del visor sin obligar al usuario a desplazarse por un visor largo antes de acceder a los datos.

---

### B. Deduplicación Probabilística con Splink y Comparación de SKUs
Se integró el modelo Fellegi-Sunter mediante DuckDB en memoria en `src/aeat_hub/linkage_facturas.py` y `src/aeat_hub/dedupe.py`:

1. **Comparación de Líneas y SKUs (`CustomLevel` DuckDB)**
   - Extrae los códigos/SKUs de las líneas de cada factura (`asiento.lineas`).
   - Calcula la intersección de listas en DuckDB: `len(list_intersect(try_cast(skus_l as VARCHAR[]), try_cast(skus_r as VARCHAR[])))`.
   - **Pesos calibrados (en bits):**
     - $\ge 2$ SKUs idénticos: $+10.81\text{ bits}$ ($m=0.90, u=0.0005$).
     - $1$ SKU idéntico: $+3.00\text{ bits}$ ($m=0.70, u=0.087$).
     - Sin SKUs coincidentes: nivel neutro ($0.0\text{ bits}$).
2. **Penalización por Importe Distinto**
   - Penalización aumentada ($m=0.00005, u=0.999$, $-14.28\text{ bits}$) para neutralizar falsos positivos entre compras distintas hechas en la misma tienda el mismo día ($78\% \rightarrow 0\%$).
3. **Explicabilidad en UI**
   - `score_par_splink` genera el desglose legible de la coincidencia, integrado tanto en los desplegables de fusión como en los banners de advertencia (ej. `"Splink 100 % (2 SKUs idénticos (+10.8b))"`).
4. **Ventana de 60 Días para Tickets Canónicos**
   - Ampliación de la ventana de detección a 60 días para casos donde un ticket de tienda emitido en el momento es canjeado posteriormente por una factura oficial con número y fecha distinta pero mismo NIF, total y artículos.

---

### C. Unificación de Confianza y Calidad
- Implementación de `_asiento_badge(item)` en `src/aeat_hub/dashboard.py` como única fuente de verdad para los chips de calidad tanto en la tabla del Libro como en las tarjetas del tablero Kanban.
- Diferenciación clara entre fallos críticos de validez fiscal (falta de NIF, emisor, fecha, total descuadrado) y avisos opcionales de codificación (artículos sin SKU), evitando que servicios no codificados degraden artificialmente la confianza del asiento.

---

### D. OCR Multimodal Gemini 2.5 Flash y Subida Drag-and-Drop
- Soporte para extracción estructurada directa mediante Gemini 2.5 Flash (`src/aeat_hub/ocr_gemini.py`) con fallback automático a la cascada local (RapidOCR / Vision).
- Endpoint `/api/upload` con soporte para arrastrar y soltar facturas en el navegador, ingestión asíncrona y registro en auditoría.

---

## 3. Estado de la Suite de Pruebas

Se añadieron tests específicos para las nuevas funcionalidades en `tests/test_dashboard.py`:
- `test_ficha_asiento_split_view_con_documento`: Comprueba renderizado de `ficha-split`, visor PDF `<iframe>`, botones de alternancia y barra de herramientas.
- `test_ficha_asiento_reabrir_y_alerta_duplicado`: Valida transiciones de estado, botones de validación y alerta con score Splink.

```bash
uv run pytest
# 177 passed, 5 warnings in 11.16s (100% OK)
```

---

## 4. Próximos Pasos Recomendados

1. **Publicación en repositorio remoto:**
   ```bash
   git push origin develop
   ```
2. **Revisión en navegador:**
   Probar la experiencia de usuario navegando a `http://127.0.0.1:8765/asiento/7` y comprobar la fluidez del Split View y la validación en un clic.
