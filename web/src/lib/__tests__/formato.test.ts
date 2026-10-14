import { describe, expect, it } from "vitest";

import { euros, fecha, porcentaje, signo } from "../formato";

describe("euros (igual que format_euro en Python)", () => {
  it.each([
    ["1362.73", "1.362,73 €"],
    ["0.30", "0,30 €"],
    ["-12.50", "-12,50 €"],
    ["1234567.8", "1.234.567,80 €"],
    ["100", "100,00 €"],
    ["-0.00", "0,00 €"],
    ["0001500.00", "1.500,00 €"],
  ])("%s → %s", (entrada, esperado) => {
    expect(euros(entrada)).toBe(esperado);
  });

  it("vacío", () => {
    expect(euros(null)).toBe("—");
  });

  it("no pierde céntimos con importes grandes (sin float)", () => {
    expect(euros("90071992547409.93")).toBe("90.071.992.547.409,93 €");
  });
});

describe("otros formatos", () => {
  it("porcentaje", () => {
    expect(porcentaje("21.00")).toBe("21 %");
    expect(porcentaje("5.20")).toBe("5,2 %");
  });
  it("fecha", () => {
    expect(fecha("2026-03-09")).toBe("09/03/2026");
  });
  it("signo", () => {
    expect([signo("-1.00"), signo("0.00"), signo("3")]).toEqual([-1, 0, 1]);
  });
});
