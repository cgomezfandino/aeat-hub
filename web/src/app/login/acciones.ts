"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { destinoSeguro } from "@/lib/seguridad";
import { COOKIE, firmarSesion, passwordCorrecta } from "@/lib/sesion";

// Límite de intentos. La IP solo es fiable detrás de un proxy que la fije
// (Vercel: x-real-ip); sin él, una clave por IP se esquiva falseando la
// cabecera y una clave global dejaría fuera al titular. Por eso:
// - AEAT_HUB_TRUST_PROXY=1: bloqueo por IP con espera creciente.
// - Sin proxy de confianza: sin bloqueo; cada fallo espera ~1 s. La defensa
//   real es la contraseña de 16+ caracteres (fuerza bruta inviable).
const intentos = new Map<string, { n: number; hasta: number }>();
const MAX_IPS = 1000;
const ESPERA_FALLO_MS = 1000;

export type EstadoLogin = { error?: string };

async function ipDeConfianza(): Promise<string | null> {
  if (process.env.AEAT_HUB_TRUST_PROXY !== "1") return null;
  const h = await headers();
  const ip = h.get("x-real-ip") ?? h.get("x-forwarded-for")?.split(",")[0];
  return ip?.trim() || null;
}

export async function entrar(_previo: EstadoLogin, formulario: FormData): Promise<EstadoLogin> {
  const ahora = Date.now();
  const ip = await ipDeConfianza();
  const registro = ip ? (intentos.get(ip) ?? { n: 0, hasta: 0 }) : null;
  if (registro && registro.hasta > ahora) {
    return { error: "Demasiados intentos desde esta conexión. Espera unos minutos." };
  }
  if (!passwordCorrecta(String(formulario.get("password") ?? ""))) {
    await new Promise((resolver) => setTimeout(resolver, ESPERA_FALLO_MS));
    if (ip && registro) {
      const n = registro.n + 1;
      if (intentos.size >= MAX_IPS) intentos.delete(intentos.keys().next().value!);
      const espera = n >= 5 ? Math.min(60_000 * 2 ** (n - 5), 15 * 60_000) : 0;
      intentos.set(ip, { n, hasta: espera ? ahora + espera : 0 });
    }
    return { error: "Contraseña incorrecta." };
  }
  if (ip) intentos.delete(ip);
  const { valor, maxAge } = await firmarSesion();
  (await cookies()).set(COOKIE, valor, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  });
  redirect(destinoSeguro(String(formulario.get("desde") ?? "/")));
}
