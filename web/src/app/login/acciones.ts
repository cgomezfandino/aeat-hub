"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { COOKIE, firmarSesion, passwordCorrecta } from "@/lib/sesion";

const intentos = new Map<string, { n: number; hasta: number }>();

export type EstadoLogin = { error?: string };

export async function entrar(_previo: EstadoLogin, formulario: FormData): Promise<EstadoLogin> {
  const ahora = Date.now();
  const registro = intentos.get("titular") ?? { n: 0, hasta: 0 };
  if (registro.hasta > ahora) {
    return { error: "Demasiados intentos. Espera un minuto." };
  }
  if (!passwordCorrecta(String(formulario.get("password") ?? ""))) {
    const n = registro.n + 1;
    intentos.set("titular", { n, hasta: n >= 5 ? ahora + 60_000 : 0 });
    return { error: "Contraseña incorrecta." };
  }
  intentos.delete("titular");
  const { valor, maxAge } = await firmarSesion();
  (await cookies()).set(COOKIE, valor, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  });
  const desde = String(formulario.get("desde") ?? "/");
  redirect(desde.startsWith("/") && !desde.startsWith("//") ? desde : "/");
}
