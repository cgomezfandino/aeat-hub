"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

type Seccion = { ruta: string; etiqueta: string; icono: React.ReactNode; fase4?: boolean };

const I = {
  panel: <path d="M4 13h6V4H4zm10 7h6v-9h-6zM4 20h6v-4H4zm10-11h6V4h-6z" />,
  bandeja: <path d="M4 13h4l2 3h4l2-3h4M5 5h14l1 8v6H4v-6z" />,
  libros: <path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zm0 13a3 3 0 0 1 3-3h10" />,
  incidencias: <path d="M12 4 3 20h18zM12 10v4m0 3h.01" />,
  impuestos: <path d="M7 4h10v16l-5-3-5 3zM9.5 9h5m-5 3h5" />,
  ajustes: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6m7-3 2-1-2-4-2 1-2-1-1-2h-4l-1 2-2 1-2-1-2 4 2 1v2l-2 1 2 4 2-1 2 1 1 2h4l1-2 2-1 2 1 2-4-2-1z" />,
};

export function secciones(base: string): Seccion[] {
  return [
    { ruta: base, etiqueta: "Panel", icono: I.panel },
    { ruta: `${base}/bandeja`, etiqueta: "Bandeja", icono: I.bandeja },
    { ruta: `${base}/incidencias`, etiqueta: "Incidencias", icono: I.incidencias },
    { ruta: `${base}/libros`, etiqueta: "Libros", icono: I.libros, fase4: true },
    { ruta: `${base}/impuestos`, etiqueta: "Impuestos", icono: I.impuestos, fase4: true },
    { ruta: `${base}/ajustes`, etiqueta: "Ajustes", icono: I.ajustes, fase4: true },
  ];
}

function Icono({ children }: { children: React.ReactNode }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export function Navegacion({ base, avisos }: { base: string; avisos: number }) {
  const ruta = usePathname();
  const items = secciones(base).filter((s) => !s.fase4);
  const activa = (r: string) => (r === base ? ruta === base : ruta.startsWith(r));
  return (
    <>
      <nav aria-label="Secciones" className="hidden lg:block">
        <ul className="space-y-1">
          {items.map((s) => (
            <li key={s.ruta}>
              <Link
                href={s.ruta}
                aria-current={activa(s.ruta) ? "page" : undefined}
                className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-crema/80 hover:bg-navy-700 hover:text-crema aria-[current=page]:bg-navy-700 aria-[current=page]:text-crema"
              >
                <Icono>{s.icono}</Icono>
                <span className="flex-1">{s.etiqueta}</span>
                {s.etiqueta === "Incidencias" && avisos > 0 ? (
                  <span className="rounded-full bg-rosa px-2 text-xs font-bold text-navy">{avisos}</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <nav aria-label="Secciones" className="fixed inset-x-0 bottom-0 z-20 border-t border-navy-700 bg-navy lg:hidden">
        <ul className="grid grid-cols-3">
          {items.map((s) => (
            <li key={s.ruta}>
              <Link
                href={s.ruta}
                aria-current={activa(s.ruta) ? "page" : undefined}
                className="flex flex-col items-center gap-1 py-2.5 text-xs text-crema/75 aria-[current=page]:text-teal"
              >
                <Icono>{s.icono}</Icono>
                {s.etiqueta}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}

export function Selectores({
  codigo,
  ejercicio,
  actividades,
}: {
  codigo: string;
  ejercicio: number;
  actividades: { codigo: string; nombre: string; ejercicios: number[] }[];
}) {
  const router = useRouter();
  const ruta = usePathname();
  const actual = actividades.find((a) => a.codigo === codigo);
  const anos = Array.from(new Set([...(actual?.ejercicios ?? []), ejercicio, new Date().getFullYear()])).sort(
    (a, b) => b - a,
  );
  const ir = (nuevoCodigo: string, nuevoAno: number) => {
    const resto = ruta.split("/").slice(4).join("/");
    router.push(`/a/${encodeURIComponent(nuevoCodigo)}/${nuevoAno}${resto ? `/${resto}` : ""}`);
  };
  const clase = "w-full rounded-lg border border-navy-700 bg-navy-800 px-2.5 py-2 text-sm text-crema";
  return (
    <div className="grid grid-cols-[1fr_auto] gap-2">
      <label className="sr-only" htmlFor="sel-actividad">Expediente</label>
      <select id="sel-actividad" className={clase} value={codigo} onChange={(e) => ir(e.target.value, ejercicio)}>
        {actividades.map((a) => (
          <option key={a.codigo} value={a.codigo}>{a.nombre}</option>
        ))}
      </select>
      <label className="sr-only" htmlFor="sel-ejercicio">Ejercicio</label>
      <select id="sel-ejercicio" className={clase} value={ejercicio} onChange={(e) => ir(codigo, Number(e.target.value))}>
        {anos.map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </select>
    </div>
  );
}
