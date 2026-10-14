import { reenviar } from "@/lib/api/cliente";
import { origenValido } from "@/lib/seguridad";

/** Reenvía los ficheros a la API con el token, sin exponerlo al navegador. */
export async function POST(request: Request, ctx: { params: Promise<{ codigo: string }> }) {
  // Segunda capa (la primera es proxy.ts): solo el propio sitio sube ficheros.
  if (!origenValido("POST", request.headers.get("origin"), request.headers.get("host"))) {
    return new Response("Origen no permitido", { status: 403 });
  }
  const { codigo } = await ctx.params;
  const entrada = await request.formData();
  const salida = new FormData();
  for (const fichero of entrada.getAll("ficheros")) {
    if (fichero instanceof File) salida.append("ficheros", fichero, fichero.name);
  }
  const respuesta = await reenviar(`/api/actividades/${encodeURIComponent(codigo)}/documentos`, {
    method: "POST",
    body: salida,
  });
  return new Response(respuesta.body, { status: respuesta.status, headers: { "Content-Type": "application/json" } });
}
