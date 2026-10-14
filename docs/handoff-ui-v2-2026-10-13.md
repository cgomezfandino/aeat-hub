# Handoff — modelo + UI v2 (13 oct 2026)

Sesión en dos bloques sobre `develop`: calibración del modelo de extracción y
rediseño incremental de la UI tras `?ui=v2`. Seis commits, sin push.

## Bloque 1 — modelo (commit `6e6be29`)

- **NIF titular**: `pick_emisor_receptor(..., excluir=...)` no inventa emisor si
  el titular es el único NIF (el asiento queda pendiente). Con varios NIF y en
  JSON de Gemini no se toca nada (protege emitidas). Propagado en ingesta,
  reintento y reparse.
- **Gemini en `eval`**: motor `gemini` (+ alias `gemini-2.5-flash`, fila en
  `ocr-status`); sin key queda `unavailable`.
- **`usageMetadata`**: `OCRResult.usage` + `usage` por caso y `total_tokens` por
  motor en el JSON del informe.
- **Calibración**: el scoring acepta fechas ES/ISO (quita el falso 88% en token
  recall); el prompt refuerza `nif_receptor` en tickets retail.
- **Medición**: sonda OK (`gemini-2.5-flash`, 9 tokens); eval sintético 7/7 y
  oro real 7/7 + 7/7 (la foto pasó de 6/7 a 7/7 con el prompt nuevo).
  Gasto total de la sesión ≈ $0,06. Oro real corrido con data-dir en `/tmp` y
  `archivo/` enlazado (el sandbox no escribe en el data-dir real).

## Bloque 2 — UI v2 (commits `3894687`, `1af1826`, `4105ade`, `5f2e266`, `fa56f25`)

- **Ruta**: `?ui=v2` renderiza en fresco (libro y ficha); sin bandera, v1
  intacta desde fichero. Mismo JS: la v2 conserva todos los ids/atributos
  cableados (tablero, líneas, filtros, diálogos, visor).
- **`src/aeat_hub/static/`** + ruta `/static/`: `tokens.css`, `v2.css`,
  `logo.svg` (recibo+check), `blob.svg` (mascota). La paleta v2 vive bajo
  `body[data-ui="v2"]` porque el `:root` v1 pisaría los tokens.
- **Vistas**: masthead con marca, cola de revisión (faltas en tarjeta, vacíos
  con blob), ficha con **número editable inline** (cierra el pendiente del
  handoff del 4 oct; `PATCH` acepta `numero` vía `corregir_numero` + `Cambio`),
  libro, duplicados e insights.
- **Identidad**: mascota blob ámbar + marca (estilo claro y denso, incremental
  por vistas). Bocetos en `generated_images/` (fuera de git, a decidir).
- **Tests**: 196 passed; 7 fallos solo ambientales (puertos bloqueados en el
  sandbox; idénticos en árbol limpio). JS nuevo validado con `node --check`.

## Pendiente

1. OK visual del usuario en navegador (incluido Safari + Split View).
2. Retirar v1 y su CSS/JS inline (~150 KB) cuando haya paridad aceptada.
3. Push de `develop` (por delante de `origin/develop`, sin push en toda la sesión).
