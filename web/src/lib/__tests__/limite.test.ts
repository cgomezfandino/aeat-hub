import { describe, expect, it } from "vitest";

import { crearLimitador } from "../limite";

describe("limitador de intentos de login", () => {
  it("las comprobaciones en paralelo se serializan: ~1 fallo por intervalo", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 40, maxEnCola: 10 });
    const inicio = Date.now();
    const resultados = await Promise.all(
      Array.from({ length: 5 }, () => limitador.intentar({ verificar: () => false })),
    );
    expect(resultados.every((r) => r === "incorrecta")).toBe(true);
    expect(Date.now() - inicio).toBeGreaterThanOrEqual(5 * 40 - 5);
  });

  it("la cola anónima está acotada: el exceso se rechaza sin probar la contraseña", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 30, maxEnCola: 2 });
    let probadas = 0;
    const resultados = await Promise.all(
      Array.from({ length: 6 }, () =>
        limitador.intentar({ verificar: () => (probadas++, false) }),
      ),
    );
    expect(resultados.filter((r) => r === "ocupado").length).toBe(4);
    expect(probadas).toBe(2);
  });

  it("un dispositivo conocido no espera detrás de un ataque (sin bloqueo al titular)", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 200, maxEnCola: 50 });
    const ataque = Array.from({ length: 20 }, () => limitador.intentar({ verificar: () => false }));
    const inicio = Date.now();
    expect(await limitador.intentar({ dispositivo: true, verificar: () => true })).toBe("correcta");
    expect(Date.now() - inicio).toBeLessThan(100);
    await Promise.all(ataque);
  });

  it("el contador por IP no se pierde con peticiones simultáneas", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 1, fallosAntesDeBloquear: 3, maxEnCola: 10 });
    await Promise.all(Array.from({ length: 3 }, () => limitador.intentar({ clave: "1.2.3.4", verificar: () => false })));
    expect(await limitador.intentar({ clave: "1.2.3.4", verificar: () => true })).toBe("bloqueada");
    expect(await limitador.intentar({ clave: "5.6.7.8", verificar: () => true })).toBe("correcta");
  });

  it("un acierto no espera y limpia el contador", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 1, fallosAntesDeBloquear: 3 });
    await limitador.intentar({ clave: "9.9.9.9", verificar: () => false });
    expect(await limitador.intentar({ clave: "9.9.9.9", verificar: () => true })).toBe("correcta");
  });
});
