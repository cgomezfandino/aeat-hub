import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Aviso, Etiqueta, estadoDe, Tarjeta } from "@/components/ui";
import { api, ErrorApi, datos, type Esquemas } from "@/lib/api/cliente";
import { euros, fecha, porcentaje } from "@/lib/formato";

import { Decision, Edicion } from "./controles";

type Params = { params: Promise<{ codigo: string; ejercicio: string; id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  return { title: `Factura #${id}` };
}

const TIPOS: Record<string, string> = {
  completa: "Factura completa",
  simplificada: "Factura simplificada",
  rectificativa: "Rectificativa",
  no_factura: "No es factura",
  sin_determinar: "Tipo sin determinar",
};

function Dato({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-tenue">{etiqueta}</dt>
      <dd className="font-medium">{children || "—"}</dd>
    </div>
  );
}

export default async function Ficha({ params }: Params) {
  const { codigo: crudo, ejercicio, id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  let ficha: Esquemas["Ficha"];
  try {
    ficha = datos(await api.GET("/api/asientos/{asiento_id}", { params: { path: { asiento_id: Number(id) } } }));
  } catch (err) {
    if (err instanceof ErrorApi && err.status === 404) notFound();
    throw err;
  }
  const propias = ficha.fecha
    ? (
        await api.GET("/api/actividades/{codigo}/incidencias", {
          params: { path: { codigo: ficha.actividad }, query: { ejercicio: Number(ejercicio) } },
        })
      ).data?.filter((i) => i.asiento_id === ficha.id) ?? []
    : [];
  const base = `/a/${crudo}/${ejercicio}`;
  const esImagen = /\.(jpe?g|png|webp|heic|tiff?)$/i.test(ficha.documento_nombre ?? "");
  const ded = ficha.deducibilidad;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="xl:sticky xl:top-6 xl:h-[calc(100dvh-3rem)]">
        <Link href={`${base}/bandeja`} className="mb-3 inline-block text-sm text-teal-tinta hover:underline">← Bandeja</Link>
        {ficha.tiene_documento && !ficha.documento_disponible ? (
          <p className="rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-8 text-center text-tenue">
            El documento original ({ficha.documento_nombre}) no está en la carpeta de datos.
          </p>
        ) : ficha.tiene_documento ? (
          esImagen ? (
            // eslint-disable-next-line @next/next/no-img-element -- documento privado servido por la API, sin optimizar
            <img src={`/api/documento/${ficha.id}`} alt={`Documento original de la factura #${ficha.id}`}
              className="max-h-full w-full rounded-[var(--radius-tarjeta)] border border-borde bg-papel object-contain" />
          ) : (
            <iframe src={`/api/documento/${ficha.id}`} title={`Documento original de la factura #${ficha.id}`}
              className="h-[70dvh] w-full rounded-[var(--radius-tarjeta)] border border-borde bg-papel xl:h-[calc(100%-2rem)]" />
          )
        ) : (
          <p className="rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-8 text-center text-tenue">Sin documento original.</p>
        )}
      </div>

      <div className="space-y-5">
        <header>
          <div className="flex flex-wrap items-center gap-2">
            <Etiqueta estado={estadoDe(ficha)} />
            <span className="text-sm text-tenue">{TIPOS[ficha.tipo_factura ?? "sin_determinar"] ?? ficha.tipo_factura}</span>
            <span className="text-sm text-tenue">· {ficha.direccion === "emitida" ? "Emitida" : "Recibida"}</span>
          </div>
          <h1 className="mt-2 font-display text-3xl font-bold">{ficha.emisor || "Sin emisor"}</h1>
          <p className="importe mt-1 font-display text-2xl">{euros(ficha.total)}</p>
        </header>

        {propias.length ? (
          <div className="space-y-2">
            {propias.map((i, n) => (
              <Aviso key={n}>
                <strong>{i.titulo}.</strong> {i.detalle} {i.cita ? <span className="text-tenue">({i.cita})</span> : null}
              </Aviso>
            ))}
          </div>
        ) : null}

        <Tarjeta titulo="Decisión">
          <Decision ficha={ficha} />
        </Tarjeta>

        {ded ? (
          <Tarjeta titulo={ded.es_ingreso ? "Cómo computa" : "Qué se deduce"}>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {!ded.es_ingreso ? <Dato etiqueta={`IVA deducible (${porcentaje(ded.pct_iva)})`}>{euros(ded.iva_deducible)}</Dato> : null}
              <Dato etiqueta={ded.es_ingreso ? "Ingreso computable" : `Gasto en IRPF (${porcentaje(ded.pct_gasto)})`}>
                {euros(ded.importe_irpf)}
              </Dato>
            </dl>
            {ded.reglas.length ? (
              <ul className="mt-3 space-y-1.5 text-sm">
                {ded.reglas.map((r) => (
                  <li key={r.codigo}>{r.texto} {r.cita ? <span className="text-tenue">({r.cita})</span> : null}</li>
                ))}
              </ul>
            ) : null}
            {ded.avisos.map((a) => (
              <div key={a} className="mt-3"><Aviso>{a}</Aviso></div>
            ))}
            {!ficha.computa ? (
              <p className="mt-3 text-xs text-tenue">Así contará cuando la valides; hoy no está en el libro.</p>
            ) : null}
          </Tarjeta>
        ) : null}

        <Tarjeta titulo="Datos de la factura">
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Dato etiqueta="Serie y número">{[ficha.serie, ficha.numero].filter(Boolean).join(" ")}</Dato>
            <Dato etiqueta="Expedición">{fecha(ficha.fecha)}</Dato>
            <Dato etiqueta="Operación">{ficha.fecha_operacion ? fecha(ficha.fecha_operacion) : "La misma"}</Dato>
            <Dato etiqueta="NIF emisor">{ficha.nif_emisor}</Dato>
            <Dato etiqueta="Destinatario">{ficha.receptor}</Dato>
            <Dato etiqueta="NIF destinatario">{ficha.nif_receptor}</Dato>
            <Dato etiqueta="Rubro">{ficha.rubro}</Dato>
            <Dato etiqueta="Retención">{ficha.retencion_cuota ? `${euros(ficha.retencion_cuota)} (${porcentaje(ficha.retencion_tipo)})` : ""}</Dato>
            <Dato etiqueta="Moneda">{ficha.moneda}</Dato>
          </dl>
          {ficha.desglose_iva.length ? (
            <table className="mt-4 w-full text-sm">
              <caption className="sr-only">Desglose por tipo de IVA</caption>
              <thead className="text-left text-xs text-tenue">
                <tr><th className="py-1">Base</th><th>Tipo</th><th>Cuota</th><th>Recargo</th></tr>
              </thead>
              <tbody className="importe">
                {ficha.desglose_iva.map((d, i) => (
                  <tr key={i} className="border-t border-borde">
                    <td className="py-1.5">{euros(d.base)}</td><td>{porcentaje(d.tipo)}</td><td>{euros(d.cuota)}</td>
                    <td>{d.recargo_cuota ? euros(d.recargo_cuota) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {ficha.factura_rectificada ? (
            <p className="mt-3 text-sm">
              Rectifica a {ficha.factura_rectificada}
              {ficha.factura_rectificada_id ? (
                <> (<Link className="text-teal-tinta underline" href={`${base}/asiento/${ficha.factura_rectificada_id}`}>#{ficha.factura_rectificada_id}</Link>)</>
              ) : " (no está en el libro)"}
            </p>
          ) : null}
        </Tarjeta>

        <Tarjeta titulo="Corregir">
          <Edicion ficha={ficha} />
        </Tarjeta>

        {ficha.lineas.length ? (
          <Tarjeta titulo={`Líneas (${ficha.lineas.length})`}>
            <ul className="divide-y divide-borde text-sm">
              {ficha.lineas.map((l, i) => (
                <li key={l.id ?? i} className="flex justify-between gap-3 py-1.5">
                  <span>{l.descripcion || l.codigo || "—"}</span>
                  <span className="importe">{euros(l.importe)}</span>
                </li>
              ))}
            </ul>
          </Tarjeta>
        ) : null}

        {ficha.cambios.length ? (
          <Tarjeta titulo="Historial">
            <ul className="space-y-1 text-sm">
              {ficha.cambios.map((c, i) => (
                <li key={i}>
                  <span className="text-tenue">{c.cuando ? new Date(c.cuando).toLocaleString("es-ES") : ""}</span>{" "}
                  <strong>{c.campo}</strong>: {c.campo === "fusion" ? "fusión (reversible)" : `${c.antes || "—"} → ${c.despues || "—"}`}
                </li>
              ))}
            </ul>
          </Tarjeta>
        ) : null}
      </div>
    </div>
  );
}
