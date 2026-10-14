import { describe, expect, it } from "vitest";

import { crearLimitador } from "../limite";

describe("limitador de intentos de login", () => {
  it("las comprobaciones en paralelo se serializan: ~1 fallo por intervalo", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 40 });
    const inicio = Date.now();
    const resultados = await Promise.all(
      Array.from({ length: 5 }, () => limitador.intentar(null, () => false)),
    );
    expect(resultados.every((r) => r === "incorrecta")).toBe(true);
    // 5 fallos simultáneos tardan al menos 5 esperas, no una sola
    expect(Date.now() - inicio).toBeGreaterThanOrEqual(5 * 40 - 5);
  });

  it("el contador por IP no se pierde con peticiones simultáneas", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 1, fallosAntesDeBloquear: 3 });
    await Promise.all(Array.from({ length: 3 }, () => limitador.intentar("1.2.3.4", () => false)));
    expect(await limitador.intentar("1.2.3.4", () => true)).toBe("bloqueada");
    // otra IP no queda afectada
    expect(await limitador.intentar("5.6.7.8", () => true)).toBe("correcta");
  });

  it("un acierto no espera y limpia el contador", async () => {
    const limitador = crearLimitador({ esperaFalloMs: 1, fallosAntesDeBloquear: 3 });
    await limitador.intentar("9.9.9.9", () => false);
    expect(await limitador.intentar("9.9.9.9", () => true)).toBe("correcta");
  });
});
