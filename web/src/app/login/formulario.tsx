"use client";

import { useActionState } from "react";

import { entrar, type EstadoLogin } from "./acciones";

export function FormularioLogin({ desde }: { desde: string }) {
  const [estado, accion, enviando] = useActionState<EstadoLogin, FormData>(entrar, {});
  return (
    <form action={accion} className="mt-8 space-y-4">
      <input type="hidden" name="desde" value={desde} />
      <label className="block">
        <span className="text-sm font-medium">Contraseña</span>
        <input
          type="password"
          name="password"
          required
          autoFocus
          autoComplete="current-password"
          className="mt-1 w-full rounded-lg border border-borde-fuerte bg-papel px-3 py-2.5"
        />
      </label>
      {estado.error ? (
        <p role="alert" className="text-sm font-medium text-rosa-tinta">
          {estado.error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={enviando}
        className="w-full rounded-lg bg-navy px-4 py-2.5 font-semibold text-crema disabled:opacity-60"
      >
        {enviando ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}
