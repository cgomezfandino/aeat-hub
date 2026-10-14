"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { destinoSeguro } from "@/lib/seguridad";
import { COOKIE, firmarSesion, passwordCorrecta } from "@/lib/sesion";

// Intentos por IP: un atacante solo se bloquea a sí mismo, nunca al titular.
const intentos = new Map<string, { n: number; hasta: number }>();
const MAX_IPS = 1000;

export type EstadoLogin = { error?: string };

async function ipCliente(): Promise<string> {
  const h = await headers();
  return (h.get("x-forwarded-for")?.split(",")[0] ?? h.get("x-real-ip") ?? "local").trim();
}

export async function entrar(_previo: EstadoLogin, formulario: FormData): Promise<EstadoLogin> {
  const ahora = Date.now();
  const ip = await ipCliente();
  const registro = intentos.get(ip) ?? { n: 0, hasta: 0 };
  if (registro.hasta > ahora) {
    return { error: "Demasiados intentos desde esta conexión. Espera un minuto." };
  }
  if (!passwordCorrecta(String(formulario.get("password") ?? ""))) {
    const n = registro.n + 1;
    if (intentos.size >= MAX_IPS) intentos.delete(intentos.keys().next().value!);
    // espera creciente a partir del 5.º fallo: 1, 2, 4… minutos (máx. 15)
    const espera = n >= 5 ? Math.min(60_000 * 2 ** (n - 5), 15 * 60_000) : 0;
    intentos.set(ip, { n, hasta: espera ? ahora + espera : 0 });
    return { error: "Contraseña incorrecta." };
  }
  intentos.delete(ip);
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
