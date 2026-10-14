"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { crearLimitador } from "@/lib/limite";
import { destinoSeguro } from "@/lib/seguridad";
import { COOKIE, firmarSesion, passwordCorrecta } from "@/lib/sesion";

// Límite de intentos (src/lib/limite.ts): cola global, ~1 fallo por segundo
// aunque lleguen en paralelo. La IP solo se usa para bloquear si viene de un
// proxy de confianza (AEAT_HUB_TRUST_PROXY=1); si no, se podría falsear.
// La defensa de fondo es la contraseña de 16+ caracteres.
const limitador = crearLimitador();

export type EstadoLogin = { error?: string };

async function ipDeConfianza(): Promise<string | null> {
  if (process.env.AEAT_HUB_TRUST_PROXY !== "1") return null;
  const h = await headers();
  const ip = h.get("x-real-ip") ?? h.get("x-forwarded-for")?.split(",")[0];
  return ip?.trim() || null;
}

export async function entrar(_previo: EstadoLogin, formulario: FormData): Promise<EstadoLogin> {
  const resultado = await limitador.intentar(await ipDeConfianza(), () =>
    passwordCorrecta(String(formulario.get("password") ?? "")),
  );
  if (resultado === "bloqueada") return { error: "Demasiados intentos desde esta conexión. Espera unos minutos." };
  if (resultado === "incorrecta") return { error: "Contraseña incorrecta." };
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
