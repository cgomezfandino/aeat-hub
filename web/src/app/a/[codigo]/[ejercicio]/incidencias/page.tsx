import type { Metadata } from "next";
import Link from "next/link";

import { Cabecera } from "@/components/ui";
import { api, datos } from "@/lib/api/cliente";

export const metadata: Metadata = { title: "Incidencias" };

const GRAVEDAD = {
  bloquea: { texto: "Bloquea", clase: "bg-rosa text-navy" },
  revisar: { texto: "Revisar", clase: "bg-rosa-suave text-rosa-tinta" },
  info: { texto: "Info", clase: "bg-sage-suave text-navy" },
} as const;

export default async function Incidencias({ params }: { params: Promise<{ codigo: string; ejercicio: string }> }) {
  const { codigo: crudo, ejercicio: anoTexto } = await params;
  const codigo = decodeURIComponent(crudo);
  const ejercicio = Number(anoTexto);
  const lista = datos(
    await api.GET("/api/actividades/{codigo}/incidencias", { params: { path: { codigo }, query: { ejercicio } } }),
  );
  const base = `/a/${encodeURIComponent(codigo)}/${ejercicio}`;

  return (
    <>
      <Cabecera titulo="Incidencias" subtitulo="Todo lo que necesita tu criterio, con el motivo y la norma." />
      {lista.length === 0 ? (
        <p className="rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-8 text-center text-tenue">Nada pendiente. Buen trabajo.</p>
      ) : (
        <ul className="space-y-3">
          {lista.map((i, n) => {
            const g = GRAVEDAD[i.gravedad as keyof typeof GRAVEDAD] ?? GRAVEDAD.info;
            const destino = i.asiento_id ? `${base}/asiento/${i.asiento_id}` : null;
            return (
              <li key={`${i.tipo}-${i.asiento_id ?? "p"}-${n}`}
                className="flex flex-wrap items-start gap-3 rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-4 shadow-tarjeta">
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${g.clase}`}>{g.texto}</span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">
                    {destino ? <Link href={destino} className="hover:underline">{i.titulo}</Link> : i.titulo}
                  </p>
                  <p className="text-sm text-tenue">
                    {i.detalle} {i.cita ? <span className="whitespace-nowrap">({i.cita})</span> : null}
                  </p>
                </div>
                {i.relacionado_id ? (
                  <Link href={`${base}/asiento/${i.relacionado_id}`} className="text-sm text-teal-tinta underline">
                    Ver #{i.relacionado_id}
                  </Link>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
