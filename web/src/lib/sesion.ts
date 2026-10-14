import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";

import { jwtVerify, SignJWT } from "jose";

/**
 * Sesión de un solo usuario. Si no hay AEAT_HUB_WEB_PASSWORD la web no pide
 * login y solo debe escuchar en 127.0.0.1 (modo local). En la nube es obligatoria.
 */
export const COOKIE = "aeat_hub_sesion";
const DURACION_S = 60 * 60 * 12;

export const LONGITUD_MINIMA = 16;

export function loginActivo(): boolean {
  const password = process.env.AEAT_HUB_WEB_PASSWORD;
  if (!password) return false;
  // Con una contraseña larga la fuerza bruta es inviable aunque se falsee la IP.
  if (password.length < LONGITUD_MINIMA) {
    throw new Error(`AEAT_HUB_WEB_PASSWORD debe tener al menos ${LONGITUD_MINIMA} caracteres.`);
  }
  return true;
}

function clave(): Uint8Array {
  const secreto = process.env.AEAT_HUB_WEB_SECRET;
  if (!secreto || secreto.length < 32) {
    throw new Error("AEAT_HUB_WEB_SECRET debe tener al menos 32 caracteres cuando hay login.");
  }
  return new TextEncoder().encode(secreto);
}

export function passwordCorrecta(intento: string): boolean {
  const esperada = process.env.AEAT_HUB_WEB_PASSWORD ?? "";
  // Comparación en tiempo constante sobre resúmenes de igual longitud.
  const a = createHash("sha256").update(intento).digest();
  const b = createHash("sha256").update(esperada).digest();
  return esperada.length > 0 && timingSafeEqual(a, b);
}

export async function firmarSesion(): Promise<{ valor: string; maxAge: number }> {
  const valor = await new SignJWT({ sub: "titular" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${DURACION_S}s`)
    .sign(clave());
  return { valor, maxAge: DURACION_S };
}

export async function sesionValida(valor: string | undefined): Promise<boolean> {
  if (!valor) return false;
  try {
    await jwtVerify(valor, clave(), { algorithms: ["HS256"] });
    return true;
  } catch {
    return false;
  }
}
