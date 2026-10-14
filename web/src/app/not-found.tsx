import Link from "next/link";

export default function NoEncontrado() {
  return (
    <main className="mx-auto max-w-xl p-10">
      <h1 className="font-display text-3xl font-bold">No existe</h1>
      <p className="mt-3 text-tenue">Ese expediente, ejercicio o factura no está en el libro.</p>
      <Link href="/" className="mt-6 inline-block rounded-lg bg-navy px-4 py-2 font-semibold text-crema">Ir al inicio</Link>
    </main>
  );
}
