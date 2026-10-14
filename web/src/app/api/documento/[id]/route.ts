import { reenviar } from "@/lib/api/cliente";

export async function GET(_request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return new Response("No encontrado", { status: 404 });
  const respuesta = await reenviar(`/api/asientos/${id}/documento`);
  const cabeceras = new Headers();
  for (const clave of ["content-type", "content-disposition", "content-length"]) {
    const valor = respuesta.headers.get(clave);
    if (valor) cabeceras.set(clave, valor);
  }
  cabeceras.set("Cache-Control", "private, no-store");
  return new Response(respuesta.body, { status: respuesta.status, headers: cabeceras });
}
