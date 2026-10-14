import { type NextRequest, NextResponse } from "next/server";

import { COOKIE, loginActivo, sesionValida } from "@/lib/sesion";

/**
 * Puerta de acceso. Sin AEAT_HUB_WEB_PASSWORD (modo local, 127.0.0.1) no hay
 * login. Con ella, todo salvo /login exige una sesión firmada.
 */
export async function proxy(request: NextRequest) {
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
