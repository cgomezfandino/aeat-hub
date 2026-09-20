# Hoja de ruta

Qué **no** está en el MVP actual (v0.1.0) y se dejó fuera a propósito.

## Fuera de alcance ahora

- UI web con servidor / app móvil. El dashboard HTML es una **foto** de SQLite que se abre en el navegador, no un servicio.
- Multi-usuario, cuentas, SaaS.
- Presentación telemática (modelos 100, 130, 303, 390, 347).
- Unlimited-OCR como motor por defecto.
- APIs cloud de facturas (Azure Document Intelligence, FacturaHub, etc.).
- Cálculo automático de amortización del inmueble y de mejoras.
- CLI de proyectos de mejora (la tabla `proyectos_mejora` existe vacía de flujo).
- Libro IVA completo y tipos 21/10/4/0/exento por casilla AEAT.
- Inbox recursivo (subcarpetas).
- Watcher automático (hay que lanzar `ingest` a mano).
- Edición del Excel como maestro bidireccional.

## Siguiente bloque natural

1. Usar de verdad el lote de Valladolid (luz, agua, internet, comunidad, seguros, PVC, rentas) y ajustar palabras clave.
2. Cuando el clasificador acierte de forma estable: pantalla de revisión de pendientes (hoy se filtran en el dashboard).
3. Amortización y proyectos de mejora.
4. Libro de actividad económica + preparación 303 (sin envío).
5. Ampliar el set de oro de `aeat-hub eval` (hoy: 2 tickets Leroy + sintético). Unlimited-OCR GGUF sigue opcional.

## Aviso

La normativa de IRPF/IVA cambia. Las cuentas y textos de este repo son un **criterio de trabajo**, no un dictamen. Revisa cada asiento antes de declarar.
