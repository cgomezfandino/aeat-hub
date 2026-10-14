import "server-only";

import { readFileSync } from "node:fs";

import { connection } from "next/server";
import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./esquema";

/**
 * Cliente de la API del motor fiscal. Solo se usa en el servidor de Next:
 * el token nunca llega al navegador y la API rechaza peticiones con Origin.
 */
const API_URL = process.env.AEAT_HUB_API_URL ?? "http://127.0.0.1:8000";

function token(): string {
  const directo = process.env.AEAT_HUB_API_TOKEN?.trim();
  if (directo) return directo;
  const fichero = process.env.AEAT_HUB_API_TOKEN_FILE;
  if (fichero) return readFileSync(fichero, "utf8").trim();
  throw new Error("Falta AEAT_HUB_API_TOKEN o AEAT_HUB_API_TOKEN_FILE para hablar con la API.");
}

const autorizacion: Middleware = {
  async onRequest({ request }) {
    // Datos fiscales vivos y personales: nunca se prerenderizan ni se cachean.
    await connection();
    request.headers.set("Authorization", `Bearer ${token()}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: API_URL, cache: "no-store" });
api.use(autorizacion);

export class ErrorApi extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Devuelve los datos o lanza `ErrorApi` con el mensaje del motor. */
export function datos<T>(respuesta: { data?: T; error?: unknown; response: Response }): T {
  if (respuesta.data !== undefined && respuesta.response.ok) return respuesta.data;
  const detalle =
    typeof respuesta.error === "object" && respuesta.error && "detail" in respuesta.error
      ? String((respuesta.error as { detail: unknown }).detail)
      : respuesta.response.statusText;
  throw new ErrorApi(detalle, respuesta.response.status);
}

/** Para route handlers que reenvían ficheros (PDF, Excel) tal cual. */
export async function reenviar(ruta: string, init?: RequestInit): Promise<Response> {
  await connection();
  return fetch(`${API_URL}${ruta}`, {
    ...init,
    cache: "no-store",
    headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token()}` },
  });
}

export type Esquemas = import("./esquema").components["schemas"];
