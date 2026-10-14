import type { Metadata } from "next";
import Link from "next/link";

import { Aviso, Cabecera, Kpi, Tarjeta } from "@/components/ui";
import { api, datos } from "@/lib/api/cliente";
import { euros, mesCorto, signo } from "@/lib/formato";

export const metadata: Metadata = { title: "Panel" };

type Params = { params: Promise<{ codigo: string; ejercicio: string }> };

export default async function Panel({ params }: Params) {
  const { codigo: crudo, ejercicio: anoTexto } = await params;
  const codigo = decodeURIComponent(crudo);
  const ejercicio = Number(anoTexto);
  const r = datos(
    await api.GET("/api/actividades/{codigo}/resumen", { params: { path: { codigo }, query: { ejercicio } } }),
  );
  const base = `/a/${encodeURIComponent(codigo)}/${ejercicio}`;
  const maximo = Math.max(1, ...r.por_mes.flatMap((m) => [Number(m.ingresos), Number(m.gastos)]));

  return (
    <>
      <Cabecera titulo={`Ejercicio ${ejercicio}`} subtitulo="Solo cuenta lo que has validado. Lo demás espera en la bandeja." />

      {r.n_por_revisar > 0 ? (
        <div className="mb-6">
          <Aviso>
            <strong>Pendiente de revisar: {r.n_por_revisar} {r.n_por_revisar === 1 ? "factura" : "facturas"} · {euros(r.total_por_revisar)}</strong>
            , fuera de estas cifras hasta que las valides.{" "}
            <Link href={`${base}/bandeja`} className="font-semibold text-rosa-tinta underline underline-offset-2">
              Ir a la bandeja
            </Link>
          </Aviso>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi etiqueta="Ingresos computables" importe={r.ingresos} tono="teal" />
        <Kpi etiqueta="Gastos deducibles" importe={r.gastos} />
        <Kpi
          etiqueta="Resultado"
          importe={r.resultado}
          tono={signo(r.resultado) < 0 ? "rosa" : "sage"}
          nota="Antes de amortizaciones y reducciones"
        />
        <Kpi etiqueta="Mejoras e inversiones" importe={r.mejoras} tono="sage" nota="Se amortizan; no restan este año" />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Kpi etiqueta="IVA repercutido" importe={r.iva_repercutido} />
        <Kpi etiqueta="IVA soportado deducible" importe={r.iva_soportado_deducible} />
        <Kpi etiqueta="Retenciones que te practicaron" importe={r.retenciones_soportadas} />
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Tarjeta titulo="Mes a mes">
          <ol className="grid grid-cols-12 items-end gap-1.5" aria-label="Ingresos y gastos computables por mes">
            {r.por_mes.map((m) => (
              <li key={m.mes} className="flex flex-col items-center gap-1">
                <div className="flex h-36 w-full items-end justify-center gap-0.5">
                  <span
                    className="w-1/2 max-w-3 rounded-t bg-teal"
                    style={{ height: `${(Math.max(0, Number(m.ingresos)) / maximo) * 100}%` }}
                    title={`Ingresos ${euros(m.ingresos)}`}
                  />
                  <span
                    className="w-1/2 max-w-3 rounded-t bg-navy"
                    style={{ height: `${(Math.max(0, Number(m.gastos)) / maximo) * 100}%` }}
                    title={`Gastos ${euros(m.gastos)}`}
                  />
                </div>
                <span className="text-xs text-tenue">{mesCorto(m.mes)}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 flex gap-4 text-xs text-tenue">
            <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-teal" />Ingresos</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-navy" />Gastos</span>
          </p>
        </Tarjeta>

        <Tarjeta titulo="Para decidir">
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between"><dt>En el libro</dt><dd className="importe font-semibold">{r.n_computables}</dd></div>
            <div className="flex justify-between"><dt>Por revisar</dt><dd className="importe font-semibold">{r.n_por_revisar}</dd></div>
            <div className="flex justify-between"><dt>Incidencias</dt><dd className="importe font-semibold text-rosa-tinta">{r.n_incidencias}</dd></div>
            <div className="flex justify-between"><dt>Duplicados fusionados</dt><dd className="importe">{r.n_duplicados}</dd></div>
          </dl>
          <Link href={`${base}/incidencias`} className="mt-4 inline-block rounded-lg bg-navy px-3 py-2 text-sm font-semibold text-crema">
            Ver incidencias
          </Link>
        </Tarjeta>
      </div>

      {r.avisos.length ? (
        <div className="mt-6 space-y-2">
          {r.avisos.map((a) => (
            <Aviso key={a} tono="sage">{a}</Aviso>
          ))}
        </div>
      ) : null}
    </>
  );
}
