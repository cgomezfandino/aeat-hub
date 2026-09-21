# Rubros de gestor (nombres cortos + alta con casilla)

Fecha: 2026-09-20
Estado: hecho (PR #1, merge `ee1a69d`)

## Objetivo

El rubro es lo que usaría un gestor para ordenar facturas de gastos e ingresos, revisar calidad y ver el mes a mes. Se lee y se escribe `Hogar`. El identificador interno tipo `CI.GAS.HOGAR` no sale en dashboard, Excel, chips ni en los comandos que usa una persona.

Los defaults cubren un alquiler de vivienda (capital inmobiliario). El usuario puede crear rubros nuevos. Cada cuenta, de sistema o propia, apunta a una casilla del anexo de inmueble de la Renta. Así no hay doble conteo ni un saco «sin clasificar» por un nombre libre.

No es software oficial de la AEAT. El HTML no presenta modelos ni escribe SQLite.

## Fuera de alcance

- Crear, borrar o renombrar cuentas desde el dashboard (sigue siendo una foto de SQLite).
- Borrar o renombrar cuentas desde el CLI en esta entrega.
- Catálogo y casillas de actividad económica (los stubs `AE.*` no se rediseñan).
- Que el clasificador invente rubros nuevos; solo asigna a cuentas que ya existen.
- Reclasificar o validar desde el navegador.
- Presentación telemática del modelo 100 / 303.

Duplicados, `validado`, umbral 0,8 y el gráfico de gastos mensuales no cambian de comportamiento; solo cambian las etiquetas de rubro que muestran.

## Qué se ve

Nunca se muestra ni se pide un código `CI.*` / `AE.*` en la UI ni en el CLI de uso diario.

| Superficie | Rubro |
| --- | --- |
| Libro (columna y filtros) | Nombre corto. El filtro usa el nombre; un `data-*` interno puede seguir llevando el id, pero no se pinta. |
| Mix por rubro y gastos del mes | Nombre corto (`Luz` distinto de `Agua`). |
| Pop-up de confianza | Nombre corto. Línea secundaria: casilla de la Renta. Sin código. |
| Chips de reclasificar en Revisar | Hogar / Reparación / Mejora. Copian `aeat-hub reclasificar <id> Hogar` (nombre, no código). |
| Excel | Solo columna `rubro` (nombre corto). Sin columna de código. |
| CLI `cuentas` | Nombre, casilla, tipo, origen (`sistema` / `usuario`). Sin columna de código. |
| CLI `asientos` | Nombre corto. |
| Logs de desarrollo | Pueden citar el id interno; no es superficie de usuario. |

Los asientos siguen guardando el id interno en `cuenta_codigo`. No se reescriben las filas ya clasificadas.

## Catálogo de salida (capital inmobiliario)

Lo que existe al hacer `init`. El usuario solo ve la columna Nombre. El id interno no se publica en docs de uso ni en la UI; se conserva en SQLite para no romper asientos ya guardados.

| Nombre | Casilla Renta | Tipo |
| --- | --- | --- |
| Alquiler | `ingresos` | ingreso |
| Indemnización | `ingresos` | ingreso |
| Luz | `suministros` | gasto |
| Agua | `suministros` | gasto |
| Internet | `suministros` | gasto |
| Comunidad | `comunidad` | gasto |
| Seguro | `seguros` | gasto |
| IBI | `ibi` | gasto |
| Hogar | `otros` | gasto |
| Reparación | `reparacion` | gasto |
| Intereses | `intereses` | gasto |
| Administración | `admin` | gasto |
| Ventanas | `mejoras` | mejora |
| Suelo | `mejoras` | mejora |
| Revestimientos | `mejoras` | mejora |
| Mano de obra | `mejoras` | mejora |
| Otras mejoras | `mejoras` | mejora |
| Amortización | `amortizacion` | amortizacion |

Luz, Agua e Internet se quedan separados en el libro y en el mes a mes. Hacienda los junta en `suministros` al agrupar casillas. Reparación / Hogar / Mejora se mantienen: es donde un gestor evita capitalizar mal o meter un ticket de Leroy como reforma.

Los stubs de actividad económica no se rediseñan. En CLI/dashboard, si algún día se listan, también salen por nombre (`Ventas`, etc.), no por id. `casilla` queda vacía en esas filas.

## Modelo de datos

Tabla `cuentas`:

| Campo | Qué es |
| --- | --- |
| `codigo` | PK interno, opaco. Máximo 32 caracteres. No se muestra. |
| `nombre` | Etiqueta corta visible. |
| `tipo` | `ingreso` / `gasto` / `mejora` / `amortizacion`. |
| `regimen` | `capital_inmobiliario` o `actividad_economica`. |
| `notas` | Criterio (suministros del arrendador, art. 23, etc.). |
| `casilla` | Clave de `CASILLAS_CI` o vacío (solo stubs AE). |
| `sistema` | `true` si viene de `ACCOUNT_DEFS`; `false` si la creó el usuario. |

Migración SQLite (mismo patrón que `validado`): `ALTER TABLE` de `casilla` (texto, default `''`) y `sistema` (boolean, default `1` porque las filas actuales son del catálogo). Después, `seed` rellena `casilla` y pone `sistema=1` en los códigos de `ACCOUNT_DEFS`.

`seed_cuentas`:

- Si el código no existe: inserta con todos los campos.
- Si existe y `sistema=1`: actualiza `nombre`, `notas`, `tipo`, `casilla`. No pisa cuentas con `sistema=0`.
- No borra cuentas de usuario.
- No cambia el `codigo` de filas ya insertadas.

Agrupación IRPF: `casilla_clave` lee `Cuenta.casilla`. Si el asiento no tiene cuenta, o la cuenta no tiene casilla, `sin_clasificar`. El prefijo interno de mejoras deja de ser la fuente de verdad (una mejora de usuario también lleva `casilla=mejoras`). El mapa estático código→casilla se sustituye por el campo en SQLite; `ACCOUNT_DEFS` sigue siendo el origen al sembrar.

## Alta de rubros

```text
aeat-hub cuenta alta --nombre Pintura --casilla reparacion
```

Opciones:

| Opción | Regla |
| --- | --- |
| `--nombre` | Obligatorio. Visible en dashboard. No puede coincidir, en el mismo régimen, con otro `nombre` (comparación sin distinguir mayúsculas). |
| `--casilla` | Obligatorio. Una clave de `CASILLAS_CI` excepto `sin_clasificar`. |
| `--regimen` | Por defecto `capital_inmobiliario`. Esta entrega no da de alta en `actividad_economica`. |

Tipo: sale de la casilla, no se pide.

| Casilla | Tipo |
| --- | --- |
| `ingresos` | ingreso |
| `mejoras` | mejora |
| `amortizacion` | amortizacion |
| `intereses`, `reparacion`, `ibi`, `comunidad`, `seguros`, `suministros`, `admin`, `otros` | gasto |

Id interno generado (opaco): prefijo según tipo + slug del nombre en ASCII mayúsculas, sin acentos, solo `[A-Z0-9]`, recortado a 32 caracteres. Si chocara con un id ya usado, se añade un sufijo numérico. El usuario no ve este valor; el comando confirma `Creada Pintura · reparación · gasto`.

`sistema=0`. Carpeta de archivo: el slug de siempre (`filing.rubro_slug`), p. ej. `gasto/pintura`.

Errores (exit ≠ 0, sin commit):

- Casilla desconocida o `sin_clasificar`.
- Nombre duplicado en el régimen.
- `--regimen actividad_economica` en esta entrega.

`aeat-hub cuentas` lista nombre, casilla, tipo y origen (`sistema` / `usuario`).

No hay `cuenta borrar` ni `cuenta renombrar`.

## Clasificación y calidad

El agente solo asigna cuentas que existen. Un rubro nuevo no se usa hasta:

1. `cuenta alta`, y
2. `reclasificar <id> Pintura` (nombre del rubro; aprende el NIF del emisor, como ahora).

`reclasificar` resuelve el nombre al id interno (mismo régimen que la actividad del asiento, sin distinguir mayúsculas). Si hay dos cuentas con el mismo nombre en regímenes distintos, gana la de la actividad. Nombre desconocido → error. No se documenta ni se pide el id interno.

Hasta entonces, Leroy sigue yendo a Hogar. Palabras clave y heurística mejora/reparación no se tocan.

`validado` sigue bloqueando emisor, fecha, importes y `cuenta_codigo`. Duplicados (hash, clave fiscal, phash, NIF+importe±3 días) no usan el rubro: no cambian. Los duplicados no entran en resúmenes ni en casillas.

## Dashboard y Excel

- Celda Rubro: solo `cuenta.nombre`. Se quita cualquier pintura del id interno.
- Filtro de cabecera: checkboxes con el nombre corto.
- Mix y barras del mes: agrupan por nombre corto (Luz distinto de Agua).
- Casillas / «Como iría en la Renta» / resumen por naturaleza: agrupan por `casilla` (Luz+Agua+Internet = Suministros). La etiqueta es la de `CASILLAS_CI`, acortada si el texto actual es legalista (`Suministros`, no `Suministros (si los paga el arrendador)`). `NATURALEZA_CI` en el dashboard se deja de usar.

Tras implementar, regenerar el HTML del expediente con `aeat-hub dashboard`.

## Tests

- Texto visible del Libro y de Revisar: `Hogar`, nunca un id `CI.*` en celdas, chips o copias de comando.
- Excel exportado: columna `rubro` = `Hogar`; no hay columna con ids `CI.*`.
- `casilla_clave` / resumen IRPF: Luz → `suministros`; cuenta de usuario Pintura con `casilla=reparacion` → `reparacion`.
- `seed` actualiza el nombre de una cuenta de sistema que en SQLite aún tenía el texto largo.
- `seed` no pisa el nombre de una cuenta `sistema=0`.
- `cuenta alta` feliz: Pintura / `reparacion` crea una cuenta tipo gasto; la salida no imprime el id interno.
- `reclasificar 12 Hogar` asigna la cuenta de sistema Hogar.
- `cuenta alta` rechaza casilla inventada y nombre duplicado.
- Un asiento `validado` no cambia de cuenta al reparse (regresión).

## Documentación de producto (en la implementación)

Actualizar `docs/modelo-fiscal.md` (nombres cortos + casilla, sin tabla de ids), `docs/cli.md` (`cuenta alta`, `reclasificar` por nombre) y `docs/clasificacion-y-duplicados.md` (ejemplos con `Hogar`, no con ids internos). Los ids pueden quedar en `docs/referencia-codigo.md` como detalle de implementación.
