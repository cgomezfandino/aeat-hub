import { describe, expect, it } from "vitest";

import { destinoSeguro, hostPermitido, hostsPermitidos, origenValido } from "../seguridad";

describe("host (DNS rebinding)", () => {
  const locales = hostsPermitidos({})!;
  it("acepta nombres locales con puerto", () => {
    expect(hostPermitido("127.0.0.1:3000", locales)).toBe(true);
    expect(hostPermitido("localhost:3000", locales)).toBe(true);
    expect(hostPermitido("[::1]:3000", locales)).toBe(true);
  });
  it("rechaza un dominio ajeno aunque resuelva a 127.0.0.1", () => {
    expect(hostPermitido("evil.example:3000", locales)).toBe(false);
    expect(hostPermitido(null, locales)).toBe(false);
  });
  it("con login y sin lista no filtra; con lista, la usa", () => {
    expect(hostsPermitidos({ AEAT_HUB_WEB_PASSWORD: "x" })).toBeNull();
    expect(hostsPermitidos({ AEAT_HUB_WEB_HOSTS: "hub.ejemplo.es" })).toEqual(["hub.ejemplo.es"]);
  });
});

describe("origen (CSRF)", () => {
  it("POST desde otra web: rechazado", () => {
    expect(origenValido("POST", "https://evil.example", "127.0.0.1:3000")).toBe(false);
  });
  it("POST del propio sitio o sin navegador: aceptado", () => {
    expect(origenValido("POST", "http://127.0.0.1:3000", "127.0.0.1:3000")).toBe(true);
    expect(origenValido("POST", null, "127.0.0.1:3000")).toBe(true);
  });
  it("GET no se filtra por origen", () => {
    expect(origenValido("GET", "https://evil.example", "127.0.0.1:3000")).toBe(true);
  });
});

describe("destino tras login (open redirect)", () => {
  it.each([
    ["/a/CI-VA-001/2026", "/a/CI-VA-001/2026"],
    ["/bandeja?vista=libro", "/bandeja?vista=libro"],
    ["//evil.com", "/"],
    ["/\\evil.com", "/"],
    ["/\\/evil.com", "/"],
    ["https://evil.com", "/"],
    ["/\tevil", "/"],
    ["", "/"],
  ])("%s → %s", (entrada, esperado) => {
    expect(destinoSeguro(entrada)).toBe(esperado);
  });
});
