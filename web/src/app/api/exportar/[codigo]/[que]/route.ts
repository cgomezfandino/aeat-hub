import { reenviar } from "@/lib/api/cliente";

const PERMITIDOS = new Set(["libros", "303", "130", "111", "115", "349", "347", "390"]);

export async function GET(request: Request, ctx: { params: Promise<{ codigo: string; que: string }> }) {
  const { codigo, que } = await ctx.params;
  if (!PERMITIDOS.has(que)) return new Response("No encontrado", { status: 404 });
  const entrada = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const clave of ["ejercicio", "trimestre"]) {
    const valor = entrada.get(clave);
    if (valor && /^\d+$/.test(valor)) query.set(clave, valor);
  }
  const respuesta = await reenviar(`/api/actividades/${encodeURIComponent(codigo)}/exportar/${que}?${query}`);
  const cabeceras = new Headers({ "Cache-Control": "private, no-store" });
  for (const clave of ["content-type", "content-disposition"]) {
    const valor = respuesta.headers.get(clave);
    if (valor) cabeceras.set(clave, valor);
  }
  return new Response(respuesta.body, { status: respuesta.status, headers: cabeceras });
}
