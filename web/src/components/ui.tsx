import { euros } from "@/lib/formato";

export function Cabecera({ titulo, subtitulo, children }: { titulo: string; subtitulo?: string; children?: React.ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">{titulo}</h1>
        {subtitulo ? <p className="mt-1 text-tenue">{subtitulo}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
    </header>
  );
}

export function Tarjeta({ titulo, children, className = "" }: { titulo?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-5 shadow-tarjeta ${className}`}>
      {titulo ? <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-tenue">{titulo}</h2> : null}
      {children}
    </section>
  );
}

type Tono = "neutro" | "teal" | "rosa" | "sage";
const TONOS: Record<Tono, string> = {
  neutro: "before:bg-navy",
  teal: "before:bg-teal",
  rosa: "before:bg-rosa",
  sage: "before:bg-sage",
};

export function Kpi({ etiqueta, importe, nota, tono = "neutro" }: { etiqueta: string; importe: string; nota?: string; tono?: Tono }) {
  return (
    <div className={`relative overflow-hidden rounded-[var(--radius-tarjeta)] border border-borde bg-papel p-4 pl-5 shadow-tarjeta before:absolute before:inset-y-0 before:left-0 before:w-1.5 ${TONOS[tono]}`}>
      <p className="text-sm text-tenue">{etiqueta}</p>
      <p className="importe mt-1 font-display text-2xl font-bold">{euros(importe)}</p>
      {nota ? <p className="mt-1 text-xs text-tenue">{nota}</p> : null}
    </div>
  );
}

type Estado = "computa" | "pendiente" | "duplicado" | "rechazado" | "aviso";
const ESTADOS: Record<Estado, { clase: string; texto: string }> = {
  computa: { clase: "bg-teal-suave text-teal-tinta", texto: "En el libro" },
  pendiente: { clase: "bg-sage-suave text-navy", texto: "Por revisar" },
  duplicado: { clase: "bg-borde text-tenue", texto: "Duplicado" },
  rechazado: { clase: "bg-borde text-tenue line-through", texto: "Rechazado" },
  aviso: { clase: "bg-rosa-suave text-rosa-tinta", texto: "Revisar" },
};

export function Etiqueta({ estado, texto }: { estado: Estado; texto?: string }) {
  const e = ESTADOS[estado];
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${e.clase}`}>
      {texto ?? e.texto}
    </span>
  );
}

export function estadoDe(fila: { computa: boolean; estado: string; validado: boolean }): Estado {
  if (fila.estado === "duplicado") return "duplicado";
  if (fila.estado === "rechazado") return "rechazado";
  return fila.computa ? "computa" : "pendiente";
}

export function Aviso({ children, tono = "rosa" }: { children: React.ReactNode; tono?: "rosa" | "sage" }) {
  const clase = tono === "rosa" ? "border-rosa bg-rosa-suave" : "border-sage bg-sage-suave";
  return (
    <div role="note" className={`rounded-xl border-l-4 px-4 py-3 text-sm ${clase}`}>
      {children}
    </div>
  );
}
