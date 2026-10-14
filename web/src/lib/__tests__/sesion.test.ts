import { beforeAll, describe, expect, it } from "vitest";

import { dispositivoValido, firmarDispositivo, firmarSesion, passwordCorrecta, sesionValida } from "../sesion";

beforeAll(() => {
  process.env.AEAT_HUB_WEB_SECRET = "x".repeat(40);
  process.env.AEAT_HUB_WEB_PASSWORD = "una-contraseña-larga-de-verdad";
});

describe("sesión y dispositivo", () => {
  it("una cookie de dispositivo NO sirve como sesión (y viceversa)", async () => {
    const dispositivo = await firmarDispositivo();
    const sesion = await firmarSesion();
    expect(await sesionValida(dispositivo.valor)).toBe(false);
    expect(await dispositivoValido(sesion.valor)).toBe(false);
    expect(await sesionValida(sesion.valor)).toBe(true);
    expect(await dispositivoValido(dispositivo.valor)).toBe(true);
  });

  it("rechaza tokens manipulados o vacíos", async () => {
    const { valor } = await firmarSesion();
    expect(await sesionValida(valor.slice(0, -2) + "xx")).toBe(false);
    expect(await sesionValida(undefined)).toBe(false);
  });

  it("compara la contraseña sin atajos", () => {
    expect(passwordCorrecta("una-contraseña-larga-de-verdad")).toBe(true);
    expect(passwordCorrecta("una-contraseña-larga-de-verdaD")).toBe(false);
    expect(passwordCorrecta("")).toBe(false);
  });
});
