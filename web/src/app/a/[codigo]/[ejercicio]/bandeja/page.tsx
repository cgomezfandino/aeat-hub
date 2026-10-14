import type { Metadata } from "next";
import Link from "next/link";

import { Subida } from "@/components/subida";
import { TablaAsientos } from "@/components/tabla-asientos";
import { Cabecera } from "@/components/ui";
import { api, datos } from "@/lib/api/cliente";

export const metadata: Metadata = { title: "Bandeja" };

const VISTAS = { por_revisar: "Por revisar", libro: "En el libro", duplicados: "Duplicados", rechazados: "Rechazados", todos: "Todos" } as const;
type Vista = keyof typeof VISTAS;

export default async function Bandeja({
  params,
  searchParams,
}: {
  params: Promise<{ codigo: string; ejercicio: string }>;
  searchParams: Promise<{ vista?: string; q?: string }>;
}) {
  const [{ codigo: crudo, ejercicio: anoTexto }, filtros] = await Promise.all([params, searchParams]);
  const codigo = decodeURIComponent(crudo);
  const ejercicio = Number(anoTexto);
  const vista: Vista = filtros.vista && filtros.vista in VISTAS ? (filtros.vista as Vista) : "por_revisar";
  const filas = datos(
    await api.GET("/api/actividades/{codigo}/asientos", {
      params: { path: { codigo }, query: { ejercicio, vista, q: filtros.q || undefined } },
    }),
  );
  const base = `/a/${encodeURIComponent(codigo)}/${ejercicio}`;

  return (
    <>
      <Cabecera titulo="Bandeja" subtitulo="Sube documentos y revisa lo que el OCR ha leído antes de que cuente." />
      <Subida codigo={codigo} base={base} />

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Filtrar" className="flex flex-wrap gap-1.5">
          {(Object.keys(VISTAS) as Vista[]).map((v) => (
            <Link
              key={v}
              href={`${base}/bandeja?vista=${v}`}
              aria-current={v === vista ? "page" : undefined}
              className="rounded-full border border-borde-fuerte px-3 py-1 text-sm aria-[current=page]:border-navy aria-[current=page]:bg-navy aria-[current=page]:text-crema"
            >
              {VISTAS[v]}
            </Link>
          ))}
        </nav>
        <form className="flex gap-2" role="search">
          <input type="hidden" name="vista" value={vista} />
          <label htmlFor="buscar" className="sr-only">Buscar</label>
          <input id="buscar" name="q" defaultValue={filtros.q} placeholder="Emisor, NIF, nº o importe"
            className="w-64 rounded-lg border border-borde-fuerte bg-papel px-3 py-1.5 text-sm" />
        </form>
      </div>
      <div className="mt-4">
        <TablaAsientos filas={filas} base={base} vacio={vista === "por_revisar" ? "Nada pendiente de revisar." : "No hay facturas en esta vista."} />
      </div>
    </>
  );
}
