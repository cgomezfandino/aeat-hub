"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { crearLimitador } from "@/lib/limite";
import { destinoSeguro } from "@/lib/seguridad";
import {
  COOKIE,
  COOKIE_DISPOSITIVO,
  dispositivoValido,
  firmarDispositivo,
  firmarSesion,
  passwordCorrecta,
} from "@/lib/sesion";

// Límite de intentos (src/lib/limite.ts): ~1 fallo/s por carril aunque lleguen
// en paralelo, cola anónima acotada y carril propio para los dispositivos que
// ya entraron (cookie firmada): un ataque no deja fuera al titular. La IP solo
// bloquea si viene de un proxy de confianza (AEAT_HUB_TRUST_PROXY=1).
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
  const almacen = await cookies();
  const conocido = await dispositivoValido(almacen.get(COOKIE_DISPOSITIVO)?.value);
  const resultado = await limitador.intentar({
    clave: await ipDeConfianza(),
    dispositivo: conocido,
    verificar: () => passwordCorrecta(String(formulario.get("password") ?? "")),
  });
  if (resultado === "bloqueada") return { error: "Demasiados intentos desde esta conexión. Espera unos minutos." };
  if (resultado === "ocupado") return { error: "Hay muchos intentos en curso. Reintenta en unos segundos." };
  if (resultado === "incorrecta") return { error: "Contraseña incorrecta." };
  const seguro = process.env.NODE_ENV === "production";
  const { valor, maxAge } = await firmarSesion();
  almacen.set(COOKIE, valor, { httpOnly: true, secure: seguro, sameSite: "lax", path: "/", maxAge });
  if (!conocido) {
    const dispositivo = await firmarDispositivo();
    almacen.set(COOKIE_DISPOSITIVO, dispositivo.valor, {
      httpOnly: true,
      secure: seguro,
      sameSite: "strict",
      path: "/login",
      maxAge: dispositivo.maxAge,
    });
  }
  redirect(destinoSeguro(String(formulario.get("desde") ?? "/")));
}
