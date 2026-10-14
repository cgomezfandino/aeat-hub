import { notFound } from "next/navigation";

import { Marca } from "@/components/marca";
import { Navegacion, Selectores } from "@/components/navegacion";
import { api, datos } from "@/lib/api/cliente";

export default async function Shell({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ codigo: string; ejercicio: string }>;
}) {
  const { codigo: crudo, ejercicio: anoTexto } = await params;
  const codigo = decodeURIComponent(crudo);
  const ejercicio = Number(anoTexto);
  if (!Number.isInteger(ejercicio)) notFound();
  const [actividades, incidencias] = await Promise.all([
    api.GET("/api/actividades").then(datos),
    api.GET("/api/actividades/{codigo}/incidencias", { params: { path: { codigo }, query: { ejercicio } } }),
  ]);
  const actividad = actividades.find((a) => a.codigo === codigo);
  if (!actividad) notFound();
  const pendientes = (incidencias.data ?? []).filter((i) => i.gravedad !== "info").length;
  const base = `/a/${encodeURIComponent(codigo)}/${ejercicio}`;

  return (
    <div className="lg:grid lg:min-h-dvh lg:grid-cols-[260px_1fr]">
      <a href="#contenido" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-crema focus:px-3 focus:py-2">
        Saltar al contenido
      </a>
      <aside className="bg-navy px-4 py-4 text-crema lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:gap-6 lg:py-6">
        <div className="flex items-center gap-3">
          <Marca />
          <div className="min-w-0">
            <p className="font-display text-lg font-bold leading-none">AEAT Hub</p>
            <p className="truncate text-xs text-crema/70">{actividad.titular || "Titular sin nombre"}</p>
          </div>
        </div>
        <div className="mt-4 lg:mt-0">
          <Selectores codigo={codigo} ejercicio={ejercicio} actividades={actividades} />
        </div>
        <Navegacion base={base} avisos={pendientes} />
        <p className="mt-auto hidden text-xs leading-relaxed text-crema/60 lg:block">
          Borradores para revisar. No es software oficial de la AEAT; nada se presenta desde aquí.
        </p>
      </aside>
      <main id="contenido" className="min-w-0 px-4 pb-24 pt-6 sm:px-8 lg:pb-10">
        {children}
      </main>
    </div>
  );
}
