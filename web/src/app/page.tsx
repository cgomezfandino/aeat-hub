import { redirect } from "next/navigation";

import { api, datos } from "@/lib/api/cliente";

export default async function Inicio() {
  const actividades = datos(await api.GET("/api/actividades"));
  const primera = actividades[0];
  if (!primera) {
    return (
      <main className="mx-auto max-w-xl p-10">
        <h1 className="font-display text-3xl font-bold">Sin expedientes</h1>
        <p className="mt-3 text-tenue">
          Crea uno con <code>aeat-hub actividad alta</code> y vuelve a cargar.
        </p>
      </main>
    );
  }
  const ejercicio = primera.ejercicios[0] ?? new Date().getFullYear();
  redirect(`/a/${encodeURIComponent(primera.codigo)}/${ejercicio}`);
}
