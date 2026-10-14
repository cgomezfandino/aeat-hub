"use client";

import { useActionState, useTransition } from "react";

import type { Esquemas } from "@/lib/api/cliente";

import {
  type EstadoAccion,
  guardar,
  marcarDuplicado,
  quitarDuplicado,
  reabrir,
  rechazar,
  validar,
} from "./acciones";

function Mensaje({ estado }: { estado: EstadoAccion }) {
  if (estado.error) return <p role="alert" className="text-sm font-semibold text-rosa-tinta">{estado.error}</p>;
  if (estado.ok) return <p role="status" className="text-sm font-medium text-teal-tinta">{estado.ok}</p>;
  return null;
}

const boton = "rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-60";

export function Decision({ ficha }: { ficha: Esquemas["Ficha"] }) {
  const [pendiente, iniciar] = useTransition();
  const [estado, setEstado] = useActionState<EstadoAccion, () => Promise<EstadoAccion>>(
    async (_p, accion) => accion(),
    {},
  );
  const [estadoRechazo, accionRechazo, rechazando] = useActionState(rechazar.bind(null, ficha.id), {});
  const correr = (accion: () => Promise<EstadoAccion>) => iniciar(() => setEstado(accion));

  if (ficha.estado === "duplicado") {
    return (
      <div className="space-y-2">
        <p className="text-sm">Duplicado de la #{ficha.duplicado_de_id}: no cuenta.</p>
        <button className={`${boton} border border-borde-fuerte`} disabled={pendiente}
          onClick={() => correr(() => quitarDuplicado(ficha.id))}>Deshacer duplicado</button>
        <Mensaje estado={estado} />
      </div>
    );
  }
  if (ficha.estado === "rechazado") {
    return (
      <div className="space-y-2">
        <p className="text-sm">Rechazada ({ficha.motivo_rechazo || "sin motivo"}): fuera del libro.</p>
        <button className={`${boton} border border-borde-fuerte`} disabled={pendiente}
          onClick={() => correr(() => reabrir(ficha.id))}>Devolver a revisión</button>
        <Mensaje estado={estado} />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {ficha.validado ? (
          <button className={`${boton} border border-borde-fuerte`} disabled={pendiente}
            onClick={() => correr(() => reabrir(ficha.id))}>Reabrir</button>
        ) : (
          <button className={`${boton} bg-teal text-navy`} disabled={pendiente}
            onClick={() => correr(() => validar(ficha.id))}>Validar: es correcta</button>
        )}
        {ficha.candidatos_duplicado.map((c) => (
          <button key={c.id} className={`${boton} border border-rosa text-rosa-tinta`} disabled={pendiente}
            onClick={() => correr(() => marcarDuplicado(ficha.id, c.id))}>
            Es duplicado de #{c.id}
          </button>
        ))}
      </div>
      <form action={accionRechazo} className="flex flex-wrap items-center gap-2">
        <label htmlFor="motivo" className="text-sm">Rechazar por</label>
        <select id="motivo" name="motivo" className="rounded-lg border border-borde-fuerte bg-papel px-2 py-1.5 text-sm">
          <option value="no-es-factura">No es una factura</option>
          <option value="calidad-datos">OCR ilegible</option>
          <option value="falta-informacion">Falta información</option>
          <option value="otro">Otro</option>
        </select>
        <button className={`${boton} border border-borde-fuerte`} disabled={rechazando}>Rechazar</button>
      </form>
      <Mensaje estado={estado} />
      <Mensaje estado={estadoRechazo} />
    </div>
  );
}

const ETIQUETAS: Record<string, string> = {
  emisor: "Emisor",
  nif_emisor: "NIF del emisor",
  numero: "Número",
  fecha: "Fecha de expedición",
  base: "Base imponible",
  iva_cuota: "Cuota de IVA",
  total: "Total",
  afectacion_pct: "Afectación a la actividad (%)",
};

export function Edicion({ ficha }: { ficha: Esquemas["Ficha"] }) {
  const [estado, accion, guardando] = useActionState(guardar.bind(null, ficha.id), {});
  const valores: Record<string, string> = {
    emisor: ficha.emisor ?? "",
    nif_emisor: ficha.nif_emisor ?? "",
    numero: ficha.numero ?? "",
    fecha: ficha.fecha ?? "",
    base: ficha.base ?? "",
    iva_cuota: ficha.iva_cuota ?? "",
    total: ficha.total ?? "",
    afectacion_pct: ficha.afectacion_pct ?? "",
  };
  return (
    <form action={accion} className="grid gap-3 sm:grid-cols-2">
      {Object.entries(ETIQUETAS).map(([campo, etiqueta]) => (
        <label key={campo} className={campo === "emisor" ? "sm:col-span-2" : ""}>
          <span className="text-xs font-medium text-tenue">{etiqueta}</span>
          <input type="hidden" name={`${campo}__antes`} value={valores[campo]} />
          <input
            name={campo}
            defaultValue={valores[campo]}
            type={campo === "fecha" ? "date" : "text"}
            inputMode={["base", "iva_cuota", "total", "afectacion_pct"].includes(campo) ? "decimal" : undefined}
            className={`mt-1 w-full rounded-lg border border-borde-fuerte bg-papel px-3 py-2 ${["base", "iva_cuota", "total"].includes(campo) ? "importe text-right" : ""}`}
          />
        </label>
      ))}
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className={`${boton} bg-navy text-crema`} disabled={guardando}>Guardar cambios</button>
        <Mensaje estado={estado} />
      </div>
      <p className="text-xs text-tenue sm:col-span-2">Guardar no valida: la factura solo cuenta cuando pulsas «Validar».</p>
    </form>
  );
}
