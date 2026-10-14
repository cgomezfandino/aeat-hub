/**
 * Limitador de intentos de login, sin carreras.
 *
 * Todas las comprobaciones pasan por una cola global: una a la vez. Cada
 * fallo retiene la cola `esperaFalloMs`, así que el ritmo máximo es ~1 fallo
 * por intervalo aunque lleguen mil peticiones en paralelo. El contador por
 * clave (IP de confianza) se actualiza antes de esperar, dentro de la cola.
 * Un acierto no espera.
 */
export type Resultado = "correcta" | "incorrecta" | "bloqueada";

export function crearLimitador({
  esperaFalloMs = 1000,
  fallosAntesDeBloquear = 5,
  bloqueoBaseMs = 60_000,
  bloqueoMaxMs = 15 * 60_000,
  maxClaves = 1000,
} = {}) {
  const registros = new Map<string, { n: number; hasta: number }>();
  let cola: Promise<unknown> = Promise.resolve();

  function enSerie<T>(tarea: () => Promise<T>): Promise<T> {
    const turno = cola.then(tarea);
    cola = turno.catch(() => undefined);
    return turno;
  }

  function intentar(clave: string | null, verificar: () => boolean): Promise<Resultado> {
    return enSerie(async () => {
      const ahora = Date.now();
      const registro = clave ? registros.get(clave) : undefined;
      if (registro && registro.hasta > ahora) return "bloqueada";
      if (verificar()) {
        if (clave) registros.delete(clave);
        return "correcta";
      }
      if (clave) {
        const n = (registro?.n ?? 0) + 1;
        if (!registro && registros.size >= maxClaves) registros.delete(registros.keys().next().value!);
        const bloqueo =
          n >= fallosAntesDeBloquear ? Math.min(bloqueoBaseMs * 2 ** (n - fallosAntesDeBloquear), bloqueoMaxMs) : 0;
        registros.set(clave, { n, hasta: bloqueo ? ahora + bloqueo : 0 });
      }
      await new Promise((resolver) => setTimeout(resolver, esperaFalloMs));
      return "incorrecta";
    });
  }

  return { intentar };
}
