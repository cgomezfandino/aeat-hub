"use server";

import { revalidatePath } from "next/cache";

import { api, ErrorApi, datos } from "@/lib/api/cliente";

export type EstadoAccion = { ok?: string; error?: string };

const CAMPOS = ["emisor", "nif_emisor", "numero", "fecha", "base", "iva_cuota", "total", "afectacion_pct"] as const;

async function patch(id: number, cuerpo: Record<string, unknown>, ok: string): Promise<EstadoAccion> {
  try {
    datos(await api.PATCH("/api/asientos/{asiento_id}", { params: { path: { asiento_id: id } }, body: cuerpo }));
  } catch (err) {
    return { error: err instanceof ErrorApi ? err.message : "No se pudo guardar." };
  }
  revalidatePath("/a/[codigo]/[ejercicio]", "layout");
  return { ok };
}

export async function guardar(id: number, _previo: EstadoAccion, formulario: FormData): Promise<EstadoAccion> {
  const cambios: Record<string, unknown> = {};
  for (const campo of CAMPOS) {
    const nuevo = formulario.get(campo);
    const antes = formulario.get(`${campo}__antes`);
    if (nuevo !== null && String(nuevo) !== String(antes ?? "")) {
      cambios[campo] = String(nuevo).trim() === "" ? null : String(nuevo).trim();
    }
  }
  if (!Object.keys(cambios).length) return { ok: "Sin cambios." };
  // Editar no valida: la validación es una decisión explícita.
  return patch(id, { ...cambios, mantener_estado: true }, "Cambios guardados.");
}

export async function validar(id: number): Promise<EstadoAccion> {
  return patch(id, { validado: true }, "Validada: ya cuenta en libros y modelos.");
}

export async function reabrir(id: number): Promise<EstadoAccion> {
  return patch(id, { validado: false }, "Devuelta a revisión.");
}

export async function rechazar(id: number, _previo: EstadoAccion, formulario: FormData): Promise<EstadoAccion> {
  const motivo = String(formulario.get("motivo") ?? "otro");
  return patch(id, { rechazar: true, motivo_rechazo: motivo }, "Rechazada: fuera del libro.");
}

export async function marcarDuplicado(id: number, destino: number): Promise<EstadoAccion> {
  return patch(id, { duplicado_de: destino }, `Marcada como duplicado de #${destino}.`);
}

export async function quitarDuplicado(id: number): Promise<EstadoAccion> {
  return patch(id, { quitar_duplicado: true }, "Duplicado deshecho.");
}
