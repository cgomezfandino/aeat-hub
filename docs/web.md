# Web (Next.js) y API

Dos procesos:

- `aeat-hub api`: FastAPI sobre el motor fiscal.
- `web/`: Next.js 16, App Router. Server Components leen de la API y Server Actions escriben en ella.

El navegador solo habla con la web, nunca con la API.

```
navegador ──► web (Next.js, :3000) ──Bearer──► API (FastAPI, :8000) ──► motor + SQLite
```

## Arrancar en local

```bash
# 1. API (aplica migraciones al arrancar; crea <data-dir>/api-token si no hay token)
uv run aeat-hub api --data-dir /Volumes/SSDCX9/data/aeat-hub

# 2. Web (solo 127.0.0.1; sin contraseña en local)
cd web
pnpm install
AEAT_HUB_API_TOKEN_FILE=/Volumes/SSDCX9/data/aeat-hub/api-token pnpm dev
```

Abre <http://127.0.0.1:3000>. Con Docker (sin probar aún en este repo):

```bash
AEAT_HUB_API_TOKEN=$(openssl rand -hex 32) AEAT_HUB_DATA_DIR=/ruta/datos docker compose up --build
```

## Seguridad

**API**
- **Token siempre:** `Authorization: Bearer`, también en local. Sin `AEAT_HUB_API_TOKEN`, se genera uno con permisos 0600.
- **Lista blanca de `Host`:** protege contra DNS rebinding.
- **Origen:** rechaza cualquier petición con cabecera `Origin`. Sin CORS, un navegador no puede llamarla.
- **Escucha:** se niega a escuchar fuera de localhost sin token.

**Web (`proxy.ts`, en este orden)**
1. **`Host` permitido (anti DNS rebinding):**
   - en local solo `127.0.0.1`, `localhost` y `[::1]`;
   - en la nube, la lista `AEAT_HUB_WEB_HOSTS` (tu dominio).
2. **Origen del propio sitio** en toda petición que cambia algo: subidas, Server Actions y login. Así se corta el CSRF. `/api/subir` lo comprueba también por su cuenta.
3. **Sesión firmada** con `AEAT_HUB_WEB_PASSWORD` (mínimo 16 caracteres; `jose`, cookie httpOnly, 12 h).
   - **Con `AEAT_HUB_TRUST_PROXY=1`** (detrás de un proxy que fija la IP real, como Vercel): bloqueo **por IP** tras 5 fallos, con espera creciente.
   - **Sin proxy de confianza:** no hay bloqueo, porque la IP se puede falsear y un bloqueo global dejaría fuera al titular. Es la longitud mínima la que hace inviable la fuerza bruta.
   - **En ambos casos:** las comprobaciones pasan **una a una** por una cola global (`web/src/lib/limite.ts`). Cada fallo la retiene ~1 s, así que lanzar peticiones en paralelo no acelera nada.
   - **Límite conocido:** la cola vive en memoria. Con varias instancias (serverless) el tope es por instancia; la contraseña larga sigue siendo la defensa de fondo.
   - La redirección tras el login solo admite rutas internas (`destinoSeguro`).

Además:
- **Token de la API:** lo usa solo el servidor (`server-only`).
- **Cabeceras:** `nosniff`, `SAMEORIGIN` y `same-origin`.
- **Pruebas:** las comprobaciones son funciones puras con tests en `web/src/lib/__tests__/seguridad.test.ts`.

**Datos**
- Los importes viajan como cadena (`"1362.73"`) y se formatean sin `float` (`web/src/lib/formato.ts`, con tests).
- Todas las páginas son dinámicas (`connection()`): ningún dato fiscal se prerenderiza ni se cachea.

## Tipos compartidos

`pnpm api:tipos` vuelca el OpenAPI de la API y genera `src/lib/api/esquema.d.ts`. Si la API cambia, `pnpm typecheck` falla en la web.

## Pantallas

**Ya disponibles:**
- **Panel:** cifras computables, pendiente de revisar, mes a mes y avisos.
- **Bandeja:** subida múltiple o desde la cámara, más vistas y búsqueda.
- **Ficha:** documento al lado, decisión (validar, rechazar, duplicado), qué se deduce y por qué, corrección (guardar **no** valida) e historial.
- **Incidencias.**

**Pendientes (fase 4):**
- Libros, Impuestos (borradores con trazabilidad) y Ajustes (perfil e inmueble).
- Gráficos, modo oscuro y atajos de teclado.

## Pendiente de plataforma

- **Rutas de los documentos:** se guardan absolutas. En un contenedor o en la nube no resuelven. Hace falta guardarlas relativas al data-dir y la interfaz `Storage` (disco / S3).
- **Postgres:** las migraciones y el tipo `Fixed` ya lo soportan, pero falta probarlo.
- **Docker:** `compose.yaml` y los Dockerfile no se han construido aún (el daemon no estaba disponible).
