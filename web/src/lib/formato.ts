/**
 * Formato es-ES exacto a partir de los importes en cadena de la API.
 * No pasa por `Number`: el mismo resultado que `format_euro` en Python.
 */
export function euros(valor: string | null | undefined, vacio = "—"): string {
  if (valor === null || valor === undefined || valor === "") return vacio;
  const texto = valor.trim();
  const negativo = texto.startsWith("-");
  const [entero = "0", decimales = ""] = texto.replace(/^[-+]/, "").split(".");
  const centimos = (decimales + "00").slice(0, 2);
  const grupos = entero.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const cero = /^0*$/.test(entero) && /^0*$/.test(centimos);
  return `${negativo && !cero ? "-" : ""}${grupos},${centimos} €`;
}

export function porcentaje(valor: string | null | undefined): string {
  if (!valor) return "—";
  const [entero, decimales = ""] = valor.split(".");
  const limpio = decimales.replace(/0+$/, "");
  return `${entero}${limpio ? `,${limpio}` : ""} %`;
}

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function fecha(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

export function mesCorto(mes: number): string {
  return MESES[mes - 1] ?? "";
}

/** Compara importes en cadena sin flotantes: signo del valor. */
export function signo(valor: string | null | undefined): -1 | 0 | 1 {
  if (!valor) return 0;
  if (/^-/.test(valor) && /[1-9]/.test(valor)) return -1;
  return /[1-9]/.test(valor) ? 1 : 0;
}
