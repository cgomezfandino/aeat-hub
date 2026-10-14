"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

type Resultado = { nombre: string; asiento_id: number | null; estado: string; detalle: string; avisos: string[] };

const ACEPTA = ".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.heic";

export function Subida({ codigo, base }: { codigo: string; base: string }) {
  const router = useRouter();
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [enviando, setEnviando] = useState<string[]>([]);
  const [resultados, setResultados] = useState<Resultado[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function subir(ficheros: FileList | File[]) {
    const lista = Array.from(ficheros);
    if (!lista.length) return;
    setError(null);
    setEnviando(lista.map((f) => f.name));
    const formulario = new FormData();
    lista.forEach((f) => formulario.append("ficheros", f, f.name));
    try {
      const respuesta = await fetch(`/api/subir/${encodeURIComponent(codigo)}`, { method: "POST", body: formulario });
      const cuerpo = await respuesta.json();
      if (!respuesta.ok) throw new Error(cuerpo.detail ?? "No se pudo subir.");
      setResultados((previos) => [...(cuerpo as Resultado[]), ...previos]);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo subir.");
    } finally {
      setEnviando([]);
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          void subir(e.dataTransfer.files);
        }}
        className={`flex flex-col items-center justify-center gap-3 rounded-[var(--radius-tarjeta)] border-2 border-dashed px-6 py-8 text-center transition-colors ${
          arrastrando ? "border-teal bg-teal-suave" : "border-borde-fuerte bg-papel"
        }`}
      >
        <svg width="56" height="40" viewBox="0 0 56 40" aria-hidden="true">
          <path d="M4 36a14 14 0 0 1 28 0z" fill="var(--color-teal)" />
          <circle cx="42" cy="12" r="8" fill="var(--color-rosa)" />
          <path d="M30 4h12L30 20z" fill="var(--color-sage)" />
        </svg>
        <p className="font-medium">Arrastra facturas o tickets (PDF o foto)</p>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => entrada.current?.click()}
            className="rounded-lg bg-navy px-4 py-2 text-sm font-semibold text-crema"
          >
            Elegir ficheros
          </button>
          <label className="cursor-pointer rounded-lg border border-borde-fuerte px-4 py-2 text-sm font-semibold sm:hidden">
            Hacer foto
            <input type="file" accept="image/*" capture="environment" className="sr-only"
              onChange={(e) => e.target.files && void subir(e.target.files)} />
          </label>
        </div>
        <input ref={entrada} type="file" multiple accept={ACEPTA} className="sr-only"
          onChange={(e) => e.target.files && void subir(e.target.files)} />
        <p className="text-xs text-tenue">Hasta 25 MB por fichero. Se lee con OCR y queda pendiente de tu revisión.</p>
      </div>

      <div aria-live="polite" className="mt-3 space-y-2">
        {enviando.length ? (
          <p className="text-sm text-tenue">Leyendo {enviando.length} {enviando.length === 1 ? "fichero" : "ficheros"}…</p>
        ) : null}
        {error ? <p role="alert" className="text-sm font-semibold text-rosa-tinta">{error}</p> : null}
        {resultados.map((r, i) => (
          <div key={`${r.nombre}-${i}`} className="rounded-lg border border-borde bg-papel px-3 py-2 text-sm">
            <p className="font-medium">
              {r.nombre} ·{" "}
              {r.asiento_id ? (
                <a className="text-teal-tinta underline" href={`${base}/asiento/${r.asiento_id}`}>#{r.asiento_id} {r.estado}</a>
              ) : (
                <span className="text-rosa-tinta">{r.detalle}</span>
              )}
            </p>
            {r.avisos.map((a) => (
              <p key={a} className="text-xs text-tenue">{a}</p>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
