import { type NextRequest, NextResponse } from "next/server";

import { COOKIE, loginActivo, sesionValida } from "@/lib/sesion";
import { hostPermitido, hostsPermitidos, origenValido } from "@/lib/seguridad";

/**
 * Puerta de acceso, en este orden:
 * 1. Host permitido (anti DNS rebinding): en local solo 127.0.0.1/localhost.
 * 2. Origen del propio sitio en peticiones que cambian algo (anti CSRF),
 *    también para las Server Actions.
 * 3. Con AEAT_HUB_WEB_PASSWORD, sesión firmada salvo en /login.
 */
export async function proxy(request: NextRequest) {
  const host = request.headers.get("host");
  const permitidos = hostsPermitidos({
    AEAT_HUB_WEB_HOSTS: process.env.AEAT_HUB_WEB_HOSTS,
    AEAT_HUB_WEB_PASSWORD: process.env.AEAT_HUB_WEB_PASSWORD,
  });
  if (permitidos && !hostPermitido(host, permitidos)) {
    return new NextResponse("Host no permitido", { status: 403 });
  }
  if (!origenValido(request.method, request.headers.get("origin"), host)) {
    return new NextResponse("Origen no permitido", { status: 403 });
  }
  if (!loginActivo()) return NextResponse.next();
  const { pathname } = request.nextUrl;
  if (pathname === "/login") return NextResponse.next();
  if (await sesionValida(request.cookies.get(COOKIE)?.value)) return NextResponse.next();
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "No autorizado" }, { status: 401 });
  }
  const login = new URL("/login", request.url);
  login.searchParams.set("desde", pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|marca.svg).*)"],
};
