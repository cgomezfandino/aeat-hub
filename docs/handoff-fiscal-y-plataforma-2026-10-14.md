# Handoff · auditoría fiscal, modelo del autónomo y plataforma web (14 oct 2026)

Sesión larga con cuatro fases planificadas. Las tres primeras están hechas y la cuarta (rediseño completo de pantallas) queda pendiente. Este documento resume:
- qué se hizo y por qué;
- cómo está el código;
- qué falta;
- qué tiene que hacer el titular.

Plan original: auditoría y paleta (navy `#0A2342`, teal `#2CA58D`, sage `#84BC9C`, crema `#FFFDF7`, rosa `#F46197`). Fases:

1. Integridad fiscal P0.
2. Modelo fiscal del autónomo.
3. Plataforma (API + Next.js).
4. Design system y pantallas.

## Estado de las ramas y PR (apiladas)

Se integran **en este orden**. Cada PR apunta a la anterior; tras fusionar una, la siguiente se retargetea a `develop`.

| PR | Rama | Contenido |
|---|---|---|
| [#5](https://github.com/cgomezfandino/aeat-hub/pull/5) | `feature/fiscal-p0-integridad` | Fase 1.2-1.4/1.6-1.7: deduplicación, importes, IVA, NIF, agregados, seguridad de subida |
| [#6](https://github.com/cgomezfandino/aeat-hub/pull/6) | `feature/fiscal-modelo-datos` | Fase 1.1: Alembic, importes exactos, campos legales, regla única de cómputo |
| [#7](https://github.com/cgomezfandino/aeat-hub/pull/7) | `feature/fiscal-gemini` | Fase 1.5: extracción Gemini con esquema y salvaguardas |
| [#8](https://github.com/cgomezfandino/aeat-hub/pull/8) | `feature/fiscal-autonomo` | Fase 2: perfil, normativa por ejercicio, deducibilidad, libros, borradores, art. 23 |
| [#9](https://github.com/cgomezfandino/aeat-hub/pull/9) | `feature/plataforma` | Fase 3: API FastAPI, web Next.js 16, Docker, CI y correcciones de seguridad |

Las pruebas pasan en todas: `uv run pytest`, más `pnpm typecheck && pnpm lint && pnpm test && pnpm build` en `web/`.

## Fase 1 · Integridad fiscal (lo que hacía perder o inventar cifras)

Cada fallo tiene un test de regresión en `tests/test_integridad_fiscal.py`. Detalle en las PR #5 y #6.

**Deduplicación**
- La agrupación por número se limita al ejercicio: la numeración reiniciada por año ya no absorbe la factura nueva.
- El nivel 2 exige el mismo emisor.
- Una sospecha (nivel 3) nunca excluye sola.
- Los rechazados no absorben re-escaneos y el phash no cruza expedientes.
- Las fusiones se pueden deshacer sin pérdidas (foto previa en `Cambio`).
- Splink recalibrado con u(NIF)=0,05 dentro de un libro: las recurrentes ya no salen duplicadas.

**Importes, fechas e IVA**
- Signos en abonos y separadores de miles.
- Fechas día/mes en el JSON del modelo.
- Ya no se inventa un 21 % de IVA cuando solo hay total.
- La base nunca se retoca para cuadrar.
- El cuadre tiene en cuenta retención y recargo.
- Los tipos coyunturales solo valen en su ventana.

**Modelo de datos**
- Alembic, con la revisión 0001 congelada como base.
- Tipo `Fixed`: céntimos enteros en SQLite y `NUMERIC` en Postgres.
- Campos legales de los art. 6, 7 y 15 del RD 1619/2012, más la tabla `asiento_iva`, rellenados con un backfill desde el JSON ya guardado.

**Regla única de cómputo** (`fiscal/computo.py`)
- Solo computa lo **validado por una persona** que no es duplicado ni rechazado.
- Lo demás se muestra siempre como «pendiente de revisar».

**Gemini**
- `responseSchema` y temperatura 0.
- Tipos `no_factura`, serie, fecha de operación, recargo, mención legal y método de rectificación.
- Confianza calculada por comprobaciones.
- La key va en cabecera y una respuesta truncada se rechaza.

**Seguridad:** subida con nombre saneado y Excel sin inyección de fórmulas.

**Decisión documentada:** no se normalizó el número de factura conservando separadores (A8). Rompía emparejamientos reales del OCR y el riesgo ya queda cubierto por el NIF, el ejercicio y el total.

## Fase 2 · Modelo fiscal del autónomo

Detalle en `docs/modelo-fiscal.md` y en la PR #8.

- **`fiscal/normativa/eAAAA.py`:**
  - casillas del 303, del 130 y de retenciones, límites y porcentajes, cada uno con su fuente;
  - 2024-2026 verificados contra la sede de la AEAT;
  - un ejercicio sin módulo usa el anterior y lo avisa;
  - **cada año hay que añadir su módulo.**
- **`fiscal/perfil.py`:** regímenes de IRPF e IVA, territorio, IAE, alta, afectación de la vivienda y rendimiento anterior. Lo no rellenado se marca como valor por defecto.
- **`fiscal/deducibilidad.py`:**
  - da por separado el IVA deducible y el gasto en IRPF, con regla y cita;
  - cubre destinatario, simplificada sin NIF, vehículo, suministros de vivienda, manutención, regímenes sin deducción, inversión, módulos, no factura y moneda.
- **`fiscal/libros.py`:** libros registro según la Orden HAC/773/2019.
- **`fiscal/modelos.py` y `fiscal/informativas.py`:**
  - borradores 303, 130, 111, 115, 347, 349 y resumen anual del IVA (base del 390);
  - trazabilidad casilla → asientos.
- **Capital inmobiliario (art. 23 LIRPF):**
  - límite de intereses + conservación con arrastre de 4 años;
  - amortización del 3 % sin suelo;
  - reducción por alquiler de vivienda;
  - cotitularidad.
- **CLI:** `actividad perfil`, `actividad inmueble`, `libros`, `modelo <n>`.

## Fase 3 · Plataforma

Detalle en `docs/web.md` y en la PR #9.

**API (`aeat-hub api`, FastAPI, `src/aeat_hub/api/`)**
- Importes como cadena JSON.
- Migra la base al arrancar.
- Token siempre obligatorio; si falta, se genera uno en `<data-dir>/api-token` con permisos 0600.
- Lista blanca de `Host` y rechazo de peticiones con `Origin`.

**Web (`web/`, Next.js 16, App Router, Tailwind 4)**
- Cliente tipado desde el OpenAPI (`pnpm api:tipos`).
- El token vive solo en el servidor y todas las rutas son dinámicas.
- Pantallas:
  - **Panel**
  - **Bandeja:** subida y cámara.
  - **Ficha:**
    - documento al lado;
    - validar, rechazar o marcar duplicado;
    - qué se deduce y por qué;
    - corregir: **guardar no valida**;
    - historial.
  - **Incidencias**
- Paleta con contraste AA verificado.

**Seguridad de la web**
- Host permitido y origen del propio sitio, comprobados en `proxy.ts`.
- Login opcional para la nube: contraseña de 16+ caracteres, sesión `jose`.
- Redirección tras el login validada después de normalizar la ruta.
- Limitador de intentos con cola acotada y carril propio para dispositivos conocidos (OWASP *device cookies*).

**Infra:** `compose.yaml` (puertos solo en 127.0.0.1), `Dockerfile.api`, `web/Dockerfile` y job de CI de la web.

**Hallazgos de la revisión de seguridad automática, todos corregidos con tests:**
- inyección de fórmulas en Excel y CSV;
- CSRF y DNS rebinding en la API, en el servidor antiguo y en la web;
- open redirect, en dos variantes;
- bloqueo del titular y carreras en el límite de login.

## Probado con la base real (siempre sobre una copia)

- Migraciones 0001 → 0004 sobre una copia de `ledger.sqlite`:
  - totales, bases, IVA, 69 líneas y 13 cambios idénticos al céntimo;
  - claves ajenas limpias.

  El primer intento falló por las FK en la recreación de tablas de SQLite. Se corrigió y está cubierto por un test.
- Recorrido completo en el navegador: se valida una factura y el pendiente pasa de 1.362,73 € a 1.348,87 €, con gastos de 13,86 €.
- **La base real no se ha tocado.** Se migrará la primera vez que se arranque la CLI o la API con el código nuevo, así que **conviene hacer copia antes**.

## Lo que tiene que hacer el titular

1. **Poner su NIF real** (hoy es `00000000T`): `aeat-hub actividad perfil --actividad CI-VA-001 --nif-titular …`. Sin él no se comprueba a nombre de quién están las facturas (art. 97 LIVA). Varias facturas indican `60052213H` como destinatario.
2. **Corregir el NIF de la factura #5** (Bricoman): `B84408229` es una mala lectura de `B84406289`.
3. **Introducir los datos del inmueble** con `aeat-hub actividad inmueble`:
   - valor catastral y de construcción (recibo del IBI);
   - coste de adquisición;
   - días arrendado;
   - % de reducción del contrato.

   Sin ellos no hay amortización, y es un gasto anual relevante.
4. **Validar las 12 facturas pendientes.** Hasta entonces, panel, libros y borradores dan 0 €.
5. **Reunir unas 30 facturas reales anonimizadas** para ampliar el set de oro y medir el prompt nuevo de Gemini. Los casos a cubrir están en `docs/evals.md`, y la evaluación cuesta unos 0,30-0,50 €.

## Pendiente técnico

**Fase 4 (no empezada)**
- Pantallas:
  - **Libros:** tablas de los libros registro con exportación.
  - **Impuestos:** borradores con trazabilidad casilla → facturas.
  - **Ajustes:** perfil, inmueble y reglas.
- Gráficos con el skill `dataviz`, modo oscuro y atajos de teclado en la bandeja (J/K, A, D, R, E).
- Estados vacíos con el motivo geométrico.
- Retirar el dashboard HTML antiguo (`dashboard.py`, `hub_http.py`) cuando haya paridad.

**Plataforma**
- **Rutas de documentos:** se guardan **absolutas**. En un contenedor o en la nube no resuelven y la ficha muestra «documento no disponible». Hay que pasarlas a relativas al data-dir e introducir `Storage` (disco / S3).
- **Docker:** `docker compose` no se ha construido (el daemon no estaba arrancado).
- **Postgres:** soportado por el tipo `Fixed` y las migraciones, pero sin probar.

**Fiscal**
- Amortización del inmovilizado de la actividad en el 130 (tabla de coeficientes y tipo de elemento).
- Compensación de cuotas de periodos anteriores en el 303 (casilla 78).
- Criterio de caja: requiere fechas de cobro y pago.
- Recargo de equivalencia de los tipos coyunturales de 2024: sin casilla verificada.
- VIES para los NIF-IVA intracomunitarios.

## Cómo arrancar

```bash
# Copia de seguridad antes de la primera ejecución con el código nuevo
cp /Volumes/SSDCX9/data/aeat-hub/db/ledger.sqlite* /ruta/copia/

uv run pytest
uv run aeat-hub api                       # http://127.0.0.1:8000 (token en <data-dir>/api-token)
cd web && pnpm install
AEAT_HUB_API_TOKEN_FILE=/Volumes/SSDCX9/data/aeat-hub/api-token pnpm dev   # http://127.0.0.1:3000
```

Sin cambios: `generated_images/` sigue sin versionar, tal como estaba al empezar.
