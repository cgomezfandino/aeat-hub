/** Marca geométrica: media luna teal, círculo rosa y triángulo sage sobre navy. */
export function Marca({ tamano = 32 }: { tamano?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="var(--color-navy-800)" />
      <path d="M14 44a18 18 0 0 1 36 0z" fill="var(--color-teal)" />
      <circle cx="44" cy="22" r="8" fill="var(--color-rosa)" />
      <path d="M14 14h18L14 32z" fill="var(--color-sage)" />
    </svg>
  );
}
