"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mx-auto max-w-xl p-10">
      <h1 className="font-display text-3xl font-bold">No se pudo cargar</h1>
      <p className="mt-3 text-tenue">
        {error.message.includes("AEAT_HUB_API") ? error.message : "El motor fiscal no responde. ¿Está arrancada la API (aeat-hub api)?"}
      </p>
      <button onClick={reset} className="mt-6 rounded-lg bg-navy px-4 py-2 font-semibold text-crema">Reintentar</button>
    </main>
  );
}
