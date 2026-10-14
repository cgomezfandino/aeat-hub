import Link from "next/link";

import { Etiqueta, estadoDe } from "@/components/ui";
import type { Esquemas } from "@/lib/api/cliente";
import { euros, fecha } from "@/lib/formato";

export function TablaAsientos({ filas, base, vacio }: { filas: Esquemas["FilaAsiento"][]; base: string; vacio: string }) {
  if (!filas.length) {
    return <p className="rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-8 text-center text-tenue">{vacio}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-[var(--radius-tarjeta)] border border-borde bg-papel shadow-tarjeta">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="border-b border-borde text-left text-xs uppercase tracking-wide text-tenue">
          <tr>
            <th scope="col" className="px-4 py-3">Fecha</th>
            <th scope="col" className="px-4 py-3">Emisor</th>
            <th scope="col" className="px-4 py-3">Nº</th>
            <th scope="col" className="px-4 py-3">Rubro</th>
            <th scope="col" className="px-4 py-3 text-right">Total</th>
            <th scope="col" className="px-4 py-3">Estado</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => (
            <tr key={f.id} className="border-b border-borde last:border-0 hover:bg-sage-suave/60">
              <td className="importe px-4 py-3">{fecha(f.fecha)}</td>
              <td className="px-4 py-3">
                <Link href={`${base}/asiento/${f.id}`} className="font-medium hover:underline">
                  {f.emisor || "Sin emisor"}
                </Link>
                <span className="block text-xs text-tenue">{f.nif_emisor || "sin NIF"}</span>
              </td>
              <td className="px-4 py-3 text-tenue">{f.numero || "—"}</td>
              <td className="px-4 py-3">{f.rubro || <span className="text-rosa-tinta">Sin rubro</span>}</td>
              <td className="importe px-4 py-3 text-right font-semibold">{euros(f.total)}</td>
              <td className="px-4 py-3">
                <Etiqueta estado={estadoDe(f)} />
                {f.duplicado_de_id && f.estado !== "duplicado" ? (
                  <span className="ml-1"><Etiqueta estado="aviso" texto={`¿Duplica #${f.duplicado_de_id}?`} /></span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
