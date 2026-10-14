import type { Metadata } from "next";

import { Marca } from "@/components/marca";

import { FormularioLogin } from "./formulario";

export const metadata: Metadata = { title: "Entrar" };

export default async function Login({ searchParams }: { searchParams: Promise<{ desde?: string }> }) {
  const { desde = "/" } = await searchParams;
  return (
    <main className="grid min-h-dvh place-items-center bg-navy p-6">
      <div className="w-full max-w-sm rounded-[var(--radius-tarjeta)] bg-crema p-8 shadow-tarjeta">
        <Marca tamano={44} />
        <h1 className="mt-6 font-display text-3xl font-bold leading-tight">AEAT Hub</h1>
        <p className="mt-1 text-tenue">Tus libros y borradores fiscales.</p>
        <FormularioLogin desde={desde} />
      </div>
    </main>
  );
}
