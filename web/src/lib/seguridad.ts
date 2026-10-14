/**
 * Comprobaciones de seguridad puras (sin dependencias de Next) para el proxy
 * y las acciones. Se prueban en src/lib/__tests__/seguridad.test.ts.
 */

export const HOSTS_LOCALES = ["127.0.0.1", "localhost", "[::1]"];

/** Nombre de host sin puerto: "127.0.0.1:3000" → "127.0.0.1", "[::1]:3000" → "[::1]". */
export function nombreHost(host: string | null | undefined): string {
  const valor = (host ?? "").trim().toLowerCase();
  if (valor.startsWith("[")) return valor.slice(0, valor.indexOf("]") + 1);
  return valor.split(":")[0];
}

/**
 * ¿Atendemos este Host? En local (sin login) solo nombres locales: así un
 * dominio ajeno que resuelva a 127.0.0.1 (DNS rebinding) no entra. Con
 * login, la lista de AEAT_HUB_WEB_HOSTS (el dominio público).
 */
export function hostPermitido(host: string | null, permitidos: string[]): boolean {
  return permitidos.includes(nombreHost(host));
}

export function hostsPermitidos(env: { AEAT_HUB_WEB_HOSTS?: string; AEAT_HUB_WEB_PASSWORD?: string }): string[] | null {
  const lista = (env.AEAT_HUB_WEB_HOSTS ?? "")
    .split(",")
    .map((h) => nombreHost(h))
    .filter(Boolean);
  if (lista.length) return lista;
  // con login y sin lista explícita no se filtra por host (la sesión protege)
  return env.AEAT_HUB_WEB_PASSWORD ? null : HOSTS_LOCALES;
}

/** Peticiones que cambian algo: el Origin, si viene, debe ser el propio sitio. */
export function origenValido(metodo: string, origen: string | null, host: string | null): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(metodo.toUpperCase())) return true;
  if (!origen) return true; // llamadas sin navegador (curl, server-to-server)
  try {
    return new URL(origen).host.toLowerCase() === (host ?? "").toLowerCase();
  } catch {
    return false;
  }
}

/** Ruta interna segura para redirigir tras el login; cualquier otra cosa → "/". */
export function destinoSeguro(desde: string | null | undefined): string {
  const valor = String(desde ?? "");
  // barras invertidas y caracteres de control: el navegador los normaliza a «//dominio»
  if (!valor.startsWith("/") || /[\\\u0000-\u001f]/.test(valor)) return "/";
  try {
    const base = "http://interno.invalid";
    const url = new URL(valor, base);
    if (url.origin !== base) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}
