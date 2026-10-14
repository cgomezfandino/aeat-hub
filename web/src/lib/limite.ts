/**
 * Limitador de intentos de login: sin carreras y sin dejar fuera al titular.
 *
 * - Carril anónimo: cola global, una comprobación a la vez; cada fallo la
 *   retiene `esperaFalloMs` (~1 fallo/s aunque lleguen en paralelo). La cola
 *   está acotada (`maxEnCola`): el exceso se rechaza al instante sin probar
 *   la contraseña, así un ataque no la hace crecer sin fin.
 * - Carril de dispositivo conocido (cookie firmada tras un login correcto,
 *   ver OWASP «device cookies»): cola propia. Un ataque desde otros clientes
 *   nunca retrasa al titular en sus dispositivos habituales.
 * - Bloqueo por clave (IP de un proxy de confianza) con espera creciente;
 *   el contador se actualiza antes de esperar, dentro de la cola.
 */
export type Resultado = "correcta" | "incorrecta" | "bloqueada" | "ocupado";

type Intento = { verificar: () => boolean; clave?: string | null; dispositivo?: boolean };

export function crearLimitador({
  esperaFalloMs = 1000,
  fallosAntesDeBloquear = 5,
  bloqueoBaseMs = 60_000,
  bloqueoMaxMs = 15 * 60_000,
  maxClaves = 1000,
  maxEnCola = 5,
} = {}) {
  const registros = new Map<string, { n: number; hasta: number }>();
  const carriles = {
    anonimo: { cola: Promise.resolve() as Promise<unknown>, pendientes: 0 },
    dispositivo: { cola: Promise.resolve() as Promise<unknown>, pendientes: 0 },
  };

  function intentar({ verificar, clave = null, dispositivo = false }: Intento): Promise<Resultado> {
    const carril = dispositivo ? carriles.dispositivo : carriles.anonimo;
    if (carril.pendientes >= maxEnCola) return Promise.resolve("ocupado");
    carril.pendientes += 1;
    const turno = carril.cola.then(async (): Promise<Resultado> => {
      try {
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
      } finally {
        carril.pendientes -= 1;
      }
    });
    carril.cola = turno.catch(() => undefined);
    return turno;
  }

  return { intentar };
}
