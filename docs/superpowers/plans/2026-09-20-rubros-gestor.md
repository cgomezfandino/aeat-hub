# Rubros de gestor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El libro muestra y acepta rubros cortos de gestor (`Hogar`, `Luz`) y permite `cuenta alta` con casilla de la Renta; el id interno no sale en UI, Excel ni CLI diario.

**Architecture:** `cuentas` gana `casilla` y `sistema`. Los asientos siguen apuntando al PK interno. El CLI resuelve por `nombre`. IRPF agrupa por `casilla`. El dashboard y el Excel pintan solo `nombre`.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Typer, SQLite, pytest, HTML estático.

**Spec:** `docs/superpowers/specs/2026-09-20-rubros-gestor-design.md`

## Global Constraints

- Superficies de usuario (dashboard, Excel, chips, `cuentas`, `asientos`, `reclasificar`, `cuenta alta`, `validar`) nunca muestran ni piden ids `CI.*` / `AE.*`. El expediente `CI-VA-001` sí puede seguir saliendo: es código de actividad, no de rubro.
- Cada cuenta de capital inmobiliario tiene `casilla` de `CASILLAS_CI` excepto `sin_clasificar`. Stubs `AE.*` dejan `casilla` vacía.
- El HTML no escribe SQLite. El alta es CLI.
- Duplicados, `validado` y el umbral 0,8 no cambian.
- No es software oficial de la AEAT. No presentar modelo 100.
- Respuestas y docs de producto en español. Commits en español, foco en el porqué.
- Tests con `uv run pytest …`. No subir facturas reales, NIF reales ni `ledger.sqlite` a git.

---

## File map

| File | Responsibility |
| --- | --- |
| `src/aeat_hub/models.py` | `Cuenta.casilla`, `Cuenta.sistema` |
| `src/aeat_hub/db.py` | `ALTER TABLE` de esas columnas |
| `src/aeat_hub/fiscal/accounts.py` | Nombres cortos, `casilla` en `AccountDef`, slug e id interno |
| `src/aeat_hub/seed.py` | Inserta nuevas; actualiza nombre/casilla si `sistema=1` |
| `src/aeat_hub/services.py` | `require_layout` siembra; `alta_cuenta`; `get_cuenta_por_nombre` |
| `src/aeat_hub/fiscal/irpf.py` | Casilla desde mapa (defs + extra DB); etiquetas cortas; chips por nombre |
| `src/aeat_hub/cli.py` | `cuenta alta`; listados y reclasificar por nombre |
| `src/aeat_hub/dashboard.py` | Celda/filtro/mix/chips/pop-up sin ids de rubro |
| `src/aeat_hub/export.py` | Columna `rubro` = nombre; Resumen_rubro por nombre |
| `docs/modelo-fiscal.md`, `docs/cli.md`, `docs/clasificacion-y-duplicados.md` | Producto sin tabla de ids |

Los tests de clasificador (`tests/test_classify.py`, ingest, filing) pueden seguir usando el PK interno: no son superficie de usuario.

---

### Task 1: Esquema, catálogo corto y seed

**Files:**
- Modify: `src/aeat_hub/models.py`
- Modify: `src/aeat_hub/db.py`
- Modify: `src/aeat_hub/fiscal/accounts.py`
- Modify: `src/aeat_hub/seed.py`
- Modify: `src/aeat_hub/services.py`
- Modify: `tests/test_seed.py`
- Modify: `docs/modelo-fiscal.md` (tabla de nombres, sin columna de código)

**Interfaces:**
- Consumes: tabla `cuentas` actual (`codigo`, `nombre`, `tipo`, `regimen`, `notas`)
- Produces: `AccountDef(codigo, nombre, tipo, regimen, notas="", casilla="")`; `Cuenta.casilla: str`; `Cuenta.sistema: bool`; `seed_cuentas(session)` actualiza filas `sistema=1`; `require_layout` llama a `seed_cuentas`

- [ ] **Step 1: Write the failing test**

En `tests/test_seed.py` deja el test existente y añade:

```python
def test_seed_nombres_cortos_y_casilla(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    assert hogar.nombre == "Hogar"
    assert hogar.casilla == "otros"
    assert hogar.sistema is True
    luz = session.get(Cuenta, "CI.GAS.LUZ")
    assert luz.nombre == "Luz"
    assert luz.casilla == "suministros"


def test_seed_no_pisa_cuenta_de_usuario(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    hogar.sistema = False
    hogar.nombre = "Bricolaje"
    session.commit()
    from aeat_hub.seed import seed_cuentas

    seed_cuentas(session)
    session.commit()
    assert session.get(Cuenta, "CI.GAS.HOGAR").nombre == "Bricolaje"


def test_seed_actualiza_nombre_largo_de_sistema(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    hogar.nombre = "Consumibles y pequeño mantenimiento del hogar"
    session.commit()
    from aeat_hub.seed import seed_cuentas

    seed_cuentas(session)
    session.commit()
    assert session.get(Cuenta, "CI.GAS.HOGAR").nombre == "Hogar"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_seed.py -q`

Expected: FAIL (`AttributeError: casilla` o `assert … == "Hogar"`).

- [ ] **Step 3: Write minimal implementation**

`Cuenta` en `src/aeat_hub/models.py`:

```python
casilla: Mapped[str] = mapped_column(String(40), default="")
sistema: Mapped[bool] = mapped_column(Boolean, default=True)
```

Importa `Boolean` de SQLAlchemy.

`_migrate` en `src/aeat_hub/db.py`: si existe `cuentas`, añade `casilla` (`VARCHAR(40) NOT NULL DEFAULT ''`) y `sistema` (`BOOLEAN NOT NULL DEFAULT 1`) si faltan.

`AccountDef` en `src/aeat_hub/fiscal/accounts.py` gana `casilla: str = ""`. Sustituye `ACCOUNT_DEFS` por:

```python
ACCOUNT_DEFS: tuple[AccountDef, ...] = (
    AccountDef("CI.ING.RENTA", "Alquiler", TIPO_INGRESO, REGIMEN_CI, casilla="ingresos"),
    AccountDef("CI.ING.INDEMN", "Indemnización", TIPO_INGRESO, REGIMEN_CI, casilla="ingresos"),
    AccountDef("CI.GAS.LUZ", "Luz", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.AGUA", "Agua", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.INTERNET", "Internet", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.COMUNIDAD", "Comunidad", TIPO_GASTO, REGIMEN_CI, casilla="comunidad"),
    AccountDef("CI.GAS.SEGURO", "Seguro", TIPO_GASTO, REGIMEN_CI, casilla="seguros"),
    AccountDef("CI.GAS.IBI", "IBI", TIPO_GASTO, REGIMEN_CI, casilla="ibi"),
    AccountDef("CI.GAS.HOGAR", "Hogar", TIPO_GASTO, REGIMEN_CI, "Pequeño mantenimiento. Revisa si es mejora.", "otros"),
    AccountDef("CI.GAS.REPARACION", "Reparación", TIPO_GASTO, REGIMEN_CI, "Art. 23 LIRPF: mantener, no revalorizar.", "reparacion"),
    AccountDef("CI.GAS.INTERES", "Intereses", TIPO_GASTO, REGIMEN_CI, casilla="intereses"),
    AccountDef("CI.GAS.ADMIN", "Administración", TIPO_GASTO, REGIMEN_CI, casilla="admin"),
    AccountDef("CI.MEJ.PVC", "Ventanas", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.SOLADO", "Suelo", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.REVEST", "Revestimientos", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.MO", "Mano de obra", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.OTROS", "Otras mejoras", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.AMO.INMUEBLE", "Amortización", TIPO_AMORT, REGIMEN_CI, "Normalmente 3 % sobre la construcción.", "amortizacion"),
    AccountDef("AE.ING.VENTAS", "Ingresos de explotación", TIPO_INGRESO, REGIMEN_AE),
    AccountDef("AE.GAS.COMPRAS", "Compras y servicios", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SUMINISTROS", "Suministros de la actividad", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SS", "Seguridad social del autónomo", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.INV.BIENES", "Bienes de inversión", TIPO_MEJORA, REGIMEN_AE),
)
```

`seed_cuentas`: para cada `AccountDef`, si no existe inserta con `casilla` y `sistema=True`. Si existe y `row.sistema` es verdadero, actualiza `nombre`, `notas`, `tipo`, `casilla`, `regimen`. No toca `sistema=False`.

`require_layout` en `src/aeat_hub/services.py`: tras `create_schema`, abre sesión, llama `seed_cuentas`, `commit`. Así un `dashboard` sobre un SQLite viejo acorta nombres.

En `docs/modelo-fiscal.md` sustituye las tablas de plan CI: columnas Nombre / Casilla Renta / Carpeta. Sin columna Código. Carpeta sigue siendo `gasto/hogar`, etc. (detalle de disco).

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_seed.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/models.py src/aeat_hub/db.py src/aeat_hub/fiscal/accounts.py src/aeat_hub/seed.py src/aeat_hub/services.py tests/test_seed.py docs/modelo-fiscal.md
git commit -m "$(cat <<'EOF'
Acorta el plan de cuentas a nombres de gestor y guarda la casilla de la Renta.

EOF
)"
```

---

### Task 2: Casilla IRPF desde la cuenta, no desde un mapa de ids

**Files:**
- Modify: `src/aeat_hub/fiscal/irpf.py`
- Modify: `tests/test_irpf.py`

**Interfaces:**
- Consumes: `AccountDef.casilla`; `Cuenta.casilla`
- Produces: `casillas_catalogo() -> dict[str, str]`; `casilla_clave(cuenta_codigo: str | None, extra: dict[str, str] | None = None) -> str`; `summarize_irpf(asientos, extra: dict[str, str] | None = None)`; `tipo_desde_casilla(clave: str) -> str`; `RUBRO_CHIPS` con nombres (`Hogar`, `Reparación`, `Otras mejoras`); etiquetas cortas en `CASILLAS_CI`

- [ ] **Step 1: Write the failing test**

Sustituye `tests/test_irpf.py` por:

```python
from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_GASTO, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.irpf import casilla_clave, summarize_irpf, tipo_desde_casilla


class _Row:
    def __init__(self, cuenta, total, estado="confirmado"):
        self.cuenta_codigo = cuenta
        self.total = total
        self.estado = estado


def test_casilla_clave_mapea_hogar_luz_y_mejoras():
    assert casilla_clave("CI.GAS.HOGAR") == "otros"
    assert casilla_clave("CI.GAS.LUZ") == "suministros"
    assert casilla_clave("CI.MEJ.PVC") == "mejoras"
    assert casilla_clave(None) == "sin_clasificar"


def test_casilla_clave_respeta_extra_de_usuario():
    extra = {"CI.GAS.PINTURA": "reparacion"}
    assert casilla_clave("CI.GAS.PINTURA", extra) == "reparacion"
    assert casilla_clave("CI.GAS.PINTURA") == "sin_clasificar"


def test_tipo_desde_casilla():
    assert tipo_desde_casilla("ingresos") == TIPO_INGRESO
    assert tipo_desde_casilla("reparacion") == TIPO_GASTO
    assert tipo_desde_casilla("mejoras") == TIPO_MEJORA


def test_summarize_irpf_no_resta_mejoras_ni_duplicados():
    rows = [
        _Row("CI.ING.RENTA", Decimal("700.00")),
        _Row("CI.GAS.LUZ", Decimal("48.40")),
        _Row("CI.GAS.HOGAR", Decimal("31.45")),
        _Row("CI.MEJ.PVC", Decimal("1452.00")),
        _Row("CI.GAS.LUZ", Decimal("48.40"), estado="duplicado"),
    ]
    summary = summarize_irpf(rows)
    assert summary["ingresos"] == Decimal("700.00")
    assert summary["gastos_deducibles"] == Decimal("79.85")
    assert summary["mejoras"] == Decimal("1452.00")
    assert summary["rendimiento"] == Decimal("620.15")
    otros = next(item for item in summary["filas"] if item["clave"] == "otros")
    assert otros["n"] == 1
    assert otros["etiqueta"] == "Otros gastos"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_irpf.py -q`

Expected: FAIL (`tipo_desde_casilla` no existe y/o etiqueta distinta).

- [ ] **Step 3: Write minimal implementation**

En `src/aeat_hub/fiscal/irpf.py`:

- Importa `ACCOUNT_DEFS`, `TIPO_AMORT`, `TIPO_GASTO`, `TIPO_INGRESO`, `TIPO_MEJORA` desde `aeat_hub.fiscal.accounts`.
- Acorta `etiqueta` de `CASILLAS_CI`: `Ingresos`, `Intereses`, `Reparación`, `IBI`, `Comunidad`, `Seguros`, `Suministros`, `Administración`, `Otros gastos`, `Amortización`, `Mejoras`, `Sin clasificar`. Deja el texto largo en `notas`.
- Borra `CUENTA_A_CASILLA`.
- Añade:

```python
def casillas_catalogo() -> dict[str, str]:
    return {item.codigo: item.casilla for item in ACCOUNT_DEFS if item.casilla}


def casilla_clave(cuenta_codigo: str | None, extra: dict[str, str] | None = None) -> str:
    if not cuenta_codigo:
        return "sin_clasificar"
    lookup = {**casillas_catalogo(), **(extra or {})}
    return lookup.get(cuenta_codigo) or "sin_clasificar"


def tipo_desde_casilla(clave: str) -> str:
    if clave == "ingresos":
        return TIPO_INGRESO
    if clave == "mejoras":
        return TIPO_MEJORA
    if clave == "amortizacion":
        return TIPO_AMORT
    return TIPO_GASTO
```

- `summarize_irpf(asientos, extra: dict[str, str] | None = None)` llama `casilla_clave(..., extra)`.
- `RUBRO_CHIPS`:

```python
RUBRO_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("Hogar", "Hogar", "Confirmar como pequeño mantenimiento"),
    ("Reparación", "Reparación", "Conservación del año (no revaloriza)"),
    ("Otras mejoras", "Mejora", "Se capitaliza; no resta del rendimiento"),
)
```

El primer campo es el **nombre** que copiará el CLI, no el PK.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_irpf.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/fiscal/irpf.py tests/test_irpf.py
git commit -m "$(cat <<'EOF'
Agrupa la Renta por casilla de la cuenta, no por un mapa de códigos.

EOF
)"
```

---

### Task 3: Alta de rubro y resolución por nombre

**Files:**
- Modify: `src/aeat_hub/fiscal/accounts.py` (slug + id interno)
- Modify: `src/aeat_hub/services.py`
- Create: `tests/test_cuentas.py`

**Interfaces:**
- Consumes: `tipo_desde_casilla`, `INDEX_CI` / claves de `CASILLAS_CI`, `REGIMEN_CI`
- Produces: `slug_cuenta(nombre: str) -> str`; `codigo_interno(nombre: str, tipo: str, regimen: str, ocupados: set[str]) -> str`; `alta_cuenta(session, *, nombre: str, casilla: str, regimen: str = REGIMEN_CI) -> Cuenta`; `get_cuenta_por_nombre(session, nombre: str, *, regimen: str) -> Cuenta`

- [ ] **Step 1: Write the failing test**

Crea `tests/test_cuentas.py`:

```python
import pytest
from sqlalchemy import select

from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, slug_cuenta
from aeat_hub.models import Cuenta
from aeat_hub.services import alta_cuenta, get_cuenta_por_nombre


def test_slug_cuenta_quita_acentos():
    assert slug_cuenta("Reparación") == "REPARACION"
    assert slug_cuenta("Pintura") == "PINTURA"


def test_alta_pintura_reparacion(session):
    cuenta = alta_cuenta(session, nombre="Pintura", casilla="reparacion")
    session.commit()
    assert cuenta.nombre == "Pintura"
    assert cuenta.casilla == "reparacion"
    assert cuenta.tipo == "gasto"
    assert cuenta.sistema is False
    assert cuenta.regimen == REGIMEN_CI
    assert get_cuenta_por_nombre(session, "pintura", regimen=REGIMEN_CI).codigo == cuenta.codigo


def test_alta_rechaza_casilla_inventada(session):
    with pytest.raises(RuntimeError, match="Casilla"):
        alta_cuenta(session, nombre="X", casilla="inventada")


def test_alta_rechaza_nombre_duplicado(session):
    with pytest.raises(RuntimeError, match="Ya existe"):
        alta_cuenta(session, nombre="Hogar", casilla="otros")


def test_alta_rechaza_actividad_economica(session):
    with pytest.raises(RuntimeError, match="capital inmobiliario"):
        alta_cuenta(session, nombre="Compras extra", casilla="otros", regimen=REGIMEN_AE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cuentas.py -q`

Expected: FAIL (import error).

- [ ] **Step 3: Write minimal implementation**

En `src/aeat_hub/fiscal/accounts.py`:

```python
import unicodedata


def slug_cuenta(nombre: str) -> str:
    decomposed = unicodedata.normalize("NFKD", nombre)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_name.upper() if ch.isalnum())


def prefijo_codigo(tipo: str, regimen: str) -> str:
    if regimen == REGIMEN_AE:
        return {"ingreso": "AE.ING", "gasto": "AE.GAS", "mejora": "AE.INV"}.get(tipo, "AE.GAS")
    return {
        "ingreso": "CI.ING",
        "gasto": "CI.GAS",
        "mejora": "CI.MEJ",
        "amortizacion": "CI.AMO",
    }[tipo]


def codigo_interno(nombre: str, tipo: str, regimen: str, ocupados: set[str]) -> str:
    prefix = prefijo_codigo(tipo, regimen)
    slug = slug_cuenta(nombre) or "RUBRO"
    base = f"{prefix}.{slug}"[:32]
    if base not in ocupados:
        return base
    for n in range(2, 1000):
        suffix = str(n)
        stem = base[: 32 - len(suffix)]
        candidate = f"{stem}{suffix}"
        if candidate not in ocupados:
            return candidate
    raise RuntimeError("No hay identificador interno libre para ese rubro.")
```

En `src/aeat_hub/services.py`:

```python
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, codigo_interno
from aeat_hub.fiscal.irpf import INDEX_CI, tipo_desde_casilla


def get_cuenta_por_nombre(session: Session, nombre: str, *, regimen: str) -> Cuenta:
    needle = nombre.strip().casefold()
    matches = [
        row
        for row in session.scalars(select(Cuenta).where(Cuenta.regimen == regimen))
        if row.nombre.casefold() == needle
    ]
    if not matches:
        raise RuntimeError(f"Rubro desconocido: {nombre}")
    if len(matches) > 1:
        raise RuntimeError(f"Hay varios rubros llamados {nombre}")
    return matches[0]


def alta_cuenta(
    session: Session,
    *,
    nombre: str,
    casilla: str,
    regimen: str = REGIMEN_CI,
) -> Cuenta:
    if regimen != REGIMEN_CI:
        raise RuntimeError("En esta versión solo se dan de alta rubros de capital inmobiliario.")
    if casilla not in INDEX_CI or casilla == "sin_clasificar":
        raise RuntimeError(f"Casilla desconocida: {casilla}")
    nombre = nombre.strip()
    if not nombre:
        raise RuntimeError("El nombre del rubro no puede estar vacío.")
    existentes = list(session.scalars(select(Cuenta).where(Cuenta.regimen == regimen)))
    if any(row.nombre.casefold() == nombre.casefold() for row in existentes):
        raise RuntimeError(f"Ya existe el rubro {nombre}")
    tipo = tipo_desde_casilla(casilla)
    ocupados = {row.codigo for row in session.scalars(select(Cuenta))}
    cuenta = Cuenta(
        codigo=codigo_interno(nombre, tipo, regimen, ocupados),
        nombre=nombre,
        tipo=tipo,
        regimen=regimen,
        casilla=casilla,
        sistema=False,
    )
    session.add(cuenta)
    session.flush()
    return cuenta
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_cuentas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/fiscal/accounts.py src/aeat_hub/services.py tests/test_cuentas.py
git commit -m "$(cat <<'EOF'
Permite crear rubros propios enganchados a una casilla de la Renta.

EOF
)"
```

---

### Task 4: CLI por nombre (`cuenta alta`, listar, reclasificar, asientos)

**Files:**
- Modify: `src/aeat_hub/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `docs/cli.md`
- Modify: `docs/clasificacion-y-duplicados.md`

**Interfaces:**
- Consumes: `alta_cuenta`, `get_cuenta_por_nombre`
- Produces: `aeat-hub cuenta alta --nombre Pintura --casilla reparacion`; `aeat-hub cuentas` sin columna de código; `aeat-hub reclasificar 12 Hogar`; `pendientes`/`duplicados` muestran nombre; `validar` cita el nombre

- [ ] **Step 1: Write the failing test**

Añade al final de `tests/test_cli.py`:

```python
def test_cli_cuentas_no_enseña_ids_internos(layout):
    runner.invoke(app, ["init", "--data-dir", str(layout.root)])
    cuentas = runner.invoke(
        app, ["cuentas", "--data-dir", str(layout.root), "--regimen", "capital_inmobiliario"]
    )
    assert cuentas.exit_code == 0, cuentas.output
    assert "Hogar" in cuentas.output
    assert "Ventanas" in cuentas.output
    assert "CI.MEJ.PVC" not in cuentas.output
    assert "CI.GAS.HOGAR" not in cuentas.output


def test_cli_cuenta_alta_y_reclasificar_por_nombre(layout, session):
    from datetime import date
    from decimal import Decimal

    from aeat_hub.models import Actividad, Asiento

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    asiento = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 5),
        ejercicio=2026,
        emisor="LEROY",
        nif_emisor="B84818442",
        total=Decimal("31.45"),
        estado="pendiente",
    )
    session.add(asiento)
    session.commit()
    asiento_id = asiento.id

    alta = runner.invoke(
        app,
        [
            "cuenta",
            "alta",
            "--data-dir",
            str(layout.root),
            "--nombre",
            "Pintura",
            "--casilla",
            "reparacion",
        ],
    )
    assert alta.exit_code == 0, alta.output
    assert "Pintura" in alta.output
    assert "CI.GAS." not in alta.output

    rec = runner.invoke(
        app,
        ["reclasificar", str(asiento_id), "Pintura", "--data-dir", str(layout.root), "--solo-este"],
    )
    assert rec.exit_code == 0, rec.output
    assert "Pintura" in rec.output
    assert "CI.GAS." not in rec.output
```

En `test_cli_init_ingest_pendientes_export` cambia `assert "CI.MEJ.PVC" in cuentas.output` por `assert "Ventanas" in cuentas.output`.

El test de alta usa el mismo `layout` que el fixture `session` (mismo `tmp_path/data`). Si el CLI `init` no se ha corrido, `require_layout` fallará: el fixture `session` ya crea esquema y seed, pero `require_layout` exige `layout.is_initialized()`. Comprueba `DataLayout.is_initialized` y, si hace falta, llama `initialize(layout)` al inicio del test en lugar de reutilizar `session`, creando el asiento vía `session_factory` tras el init:

```python
def test_cli_cuenta_alta_y_reclasificar_por_nombre(layout):
    from datetime import date
    from decimal import Decimal

    from aeat_hub.db import make_engine, session_factory
    from aeat_hub.models import Actividad, Asiento
    from aeat_hub.services import initialize

    initialize(layout)
    engine = make_engine(layout)
    factory = session_factory(engine)
    with factory() as db:
        actividad = db.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
        asiento = Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 5),
            ejercicio=2026,
            emisor="LEROY",
            nif_emisor="B84818442",
            total=Decimal("31.45"),
            estado="pendiente",
        )
        db.add(asiento)
        db.commit()
        asiento_id = asiento.id
    # … invoke cuenta alta y reclasificar como arriba
```

Usa **esta** versión del test (con `initialize`), no la que inyecta `session`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL (`No such command 'cuenta'` y/o `CI.MEJ.PVC` aún en la salida).

- [ ] **Step 3: Write minimal implementation**

En `src/aeat_hub/cli.py`:

```python
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI
from aeat_hub.services import (
    alta_actividad,
    alta_cuenta,
    get_actividad,
    get_cuenta_por_nombre,
    initialize,
    require_layout,
)

cuenta_app = typer.Typer(no_args_is_help=True, help="Plan de cuentas / rubros.")
app.add_typer(cuenta_app, name="cuenta")


@cuenta_app.command("alta")
def cuenta_alta(
    nombre: str = typer.Option(..., "--nombre"),
    casilla: str = typer.Option(..., "--casilla"),
    regimen: str = typer.Option(REGIMEN_CI, "--regimen"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Crea un rubro propio. Hay que decir a qué casilla de la Renta suma."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        try:
            cuenta = alta_cuenta(session, nombre=nombre, casilla=casilla, regimen=regimen)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(f"Creada {cuenta.nombre} · {cuenta.casilla} · {cuenta.tipo}")
```

`cuentas`: ordena por `nombre`; columnas `nombre`, `tipo`, `casilla`, `origen` (`sistema` si `row.sistema` else `usuario`). Sin `codigo`.

`reclasificar`: el argumento se llama `rubro` (`help="Nombre del rubro, p.ej. Hogar"`). Resuelve con `get_cuenta_por_nombre(session, rubro, regimen=asiento.actividad.regimen)` — carga `asiento.actividad` si hace falta (`session.get(Actividad, asiento.actividad_id)`). Mensaje: `Asiento {id} → {dest.nombre}. Validado. …`. Nada de `dest.codigo`. Captura `RuntimeError` → `typer.Exit(1)`.

`_print_asientos`: columna `rubro` con un mapa `{c.codigo: c.nombre}` de `select(Cuenta)`; muestra el nombre.

`validar`: `Rubro {nombres.get(asiento.cuenta_codigo) or 'sin cuenta'}`.

En `docs/cli.md`:

```bash
uv run aeat-hub cuenta alta --nombre Pintura --casilla reparacion
uv run aeat-hub reclasificar 12 Hogar
uv run aeat-hub reclasificar 12 Pintura --solo-este
```

Casillas válidas: las claves de `CASILLAS_CI` salvo `sin_clasificar`. Documenta `cuentas` (nombre, casilla, origen).

En `docs/clasificacion-y-duplicados.md` los ejemplos de `reclasificar` usan `Hogar` / `Reparación`, no ids. La tabla de keywords puede citar el **nombre** destino (`Luz`, `Hogar`) en vez del id.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_cli.py tests/test_cuentas.py tests/test_classify.py -q`

Expected: PASS. `test_classify.py` sigue pasando `Cuenta` por PK al `reclassify()` interno.

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/cli.py tests/test_cli.py docs/cli.md docs/clasificacion-y-duplicados.md
git commit -m "$(cat <<'EOF'
Deja el CLI en nombres de rubro para alta y reclasificar.

EOF
)"
```

---

### Task 5: Dashboard sin ids de rubro

**Files:**
- Modify: `src/aeat_hub/dashboard.py`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `cuenta.nombre`, `cuenta.casilla`, `casilla_clave(..., extra)`, `RUBRO_CHIPS` por nombre, `INDEX_CI.etiqueta`
- Produces: HTML de Libro/Revisar/mix/filtros/chips sin `CI.GAS.` / `CI.ING.` / `CI.MEJ.` / `CI.AMO.`; `data-cuenta` = nombre corto; pop-up de confianza con casilla; resumen por naturaleza = etiqueta de casilla

- [ ] **Step 1: Write the failing test**

En `tests/test_dashboard.py`:

- En `test_dashboard_kpis_excluyen_duplicados_y_mejoras` cambia las asserts de `por_naturaleza`:

```python
assert "Suministros" in labels
assert "Mejoras" in labels
assert "Otros gastos" in labels
assert "Ingresos" in labels
assert "Hogar / mantenimiento" not in labels
assert "Rentas" not in labels
```

- En `test_dashboard_html_tiene_emisor_y_fecha` sustituye las líneas de ids:

```python
assert "Hogar" in html
assert "rubro-code" not in html
assert "CI.GAS." not in html
assert "CI.MEJ." not in html
assert "CI.ING." not in html
assert "aeat-hub reclasificar" in html
assert "aeat-hub reclasificar" in html and "Hogar" in html
```

Quita `assert "CI.GAS.HOGAR" in html` y `assert "CI.GAS.REPARACION" in html`.

Añade:

```python
def test_dashboard_pop_confianza_cita_casilla(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    html = write_dashboard(session, layout, actividad, 2026).read_text(encoding="utf-8")
    assert "Otros gastos" in html or "casilla" in html.lower()
```

El pop-up debe incluir una línea `Casilla` con la etiqueta corta (p. ej. `Otros gastos` para Hogar).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py -q`

Expected: FAIL (HTML aún pinta `CI.GAS.` y `por_naturaleza` usa `NATURALEZA_CI`).

- [ ] **Step 3: Write minimal implementation**

`collect_dashboard`: carga filas `Cuenta`. Construye `nombres = {c.codigo: c.nombre}` y `extra_casillas = {c.codigo: c.casilla for c in filas if c.casilla}`. Pásalos a `_asiento_view` y a `summarize_irpf(..., extra_casillas)`. `_by_nature` usa casilla, no `NATURALEZA_CI`.

Borra el dict `NATURALEZA_CI`.

```python
def _nature_label(codigo: str | None, extra_casillas: dict[str, str]) -> str:
    if not codigo:
        return "Sin clasificar"
    from aeat_hub.fiscal.irpf import INDEX_CI, casilla_clave

    clave = casilla_clave(codigo, extra_casillas)
    meta = INDEX_CI.get(clave)
    return meta.etiqueta if meta else "Sin clasificar"
```

`_asiento_view(..., nombres, extra_casillas)`:

- `cuenta_nombre = nombres.get(codigo, "Sin clasificar")`
- `casilla = casilla_clave(codigo, extra_casillas)`
- `casilla_etiqueta = INDEX_CI[casilla].etiqueta` (con fallback `Sin clasificar`)
- Para el filtro, guarda también el nombre en el campo que irá a `data-cuenta`. Cambia `"cuenta"` del view usado en HTML a **nombre** (`cuenta_nombre` si hay cuenta, `""` si no). Si el JS de mix/filtros usa `dataset.cuenta`, que sea el nombre. El código interno no viaja al HTML.

Mix por rubro: ya suma `cuenta_nombre`; no lo cambies salvo que aún use el PK.

`_quality_cell`: en el `dl`, además de OCR y Rubro (% confianza), añade:

```html
<div><dt>Casilla</dt><dd>{etiqueta}</dd></div>
```

Usa `item["casilla_etiqueta"]`. El `dt` Rubro del pop-up sigue siendo el % de clasificación, no el nombre.

`_review_actions`:

```python
for nombre, label, title in RUBRO_CHIPS:
    if nombre == item["cuenta_nombre"]:
        continue
    cmd = f"aeat-hub reclasificar {item['id']} {nombre}"
```

Si el nombre tiene espacios (`Otras mejoras`), el comando copiado es `aeat-hub reclasificar 12 Otras mejoras`. Typer toma el resto como un argumento si se pega así en zsh **solo si va entre comillas**. Para no romper el pegado, copia:

```python
cmd = f'aeat-hub reclasificar {item["id"]} "{nombre}"'
```

siempre (también `Hogar`). El CLI recibe `Otras mejoras` entero.

`_review_row` y `_row_html`: `rubro = escape(item["cuenta_nombre"])` sin `rubro-code`.

`_ledger_filter_choices`: `rubros` = nombres únicos; `("Hogar", "Hogar")`. Orden alfabético por nombre.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_dashboard.py tests/test_irpf.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/dashboard.py tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
Muestra rubros cortos en el dashboard y oculta los ids internos.

EOF
)"
```

---

### Task 6: Excel por nombre corto

**Files:**
- Modify: `src/aeat_hub/export.py`
- Modify: `tests/test_export.py`

**Interfaces:**
- Consumes: `Cuenta.nombre`, `Cuenta.casilla`; `summarize_irpf(..., extra)`
- Produces: columna `rubro` (cabecera `Rubro`) = nombre; sin columna de PK; `Resumen_rubro` agrupa por nombre

- [ ] **Step 1: Write the failing test**

En `tests/test_export.py`:

```python
assert "Rubro" in headers
assert "Rubro / cuenta" not in headers
rubro_idx = headers.index("Rubro")
assert gastos[1][rubro_idx] == "Luz"
...
assert any(row[cuenta_idx] == "Alquiler" for row in ingresos_rows[1:])
```

Añade que ninguna celda de `Gastos` empiece por `CI.`:

```python
for row in wb["Gastos"].iter_rows(min_row=2, values_only=True):
    assert not any(isinstance(cell, str) and cell.startswith("CI.") for cell in row)
```

`Resumen_rubro`: primera columna `rubro` con `Luz`, no el PK.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export.py -q`

Expected: FAIL (`CI.GAS.LUZ` aún en la hoja).

- [ ] **Step 3: Write minimal implementation**

`export_xlsx` carga `Cuenta` y arma `nombres` + `extra_casillas`.

```python
SHEET_COLUMNS = [
    ...
    ("rubro", "Rubro"),
    ...
]
```

Quita la clave `cuenta`. `_as_row(..., nombres)`:

```python
"rubro": nombres.get(asiento.cuenta_codigo, "") if asiento.cuenta_codigo else "",
```

`_write_summary_rubro(ws, rows, nombres)`: clave `(nombres.get(codigo, "(sin rubro)"), tipo)`. Cabecera `rubro, tipo, n_asientos, …`.

`summarize_irpf(rows, extra_casillas)` en la hoja `Casillas_IRPF`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_export.py tests/test_dashboard.py -q`

Expected: PASS (`write_dashboard` llama a `export_xlsx`).

- [ ] **Step 5: Commit**

```bash
git add src/aeat_hub/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
Exporta el Excel con el nombre de rubro, sin el código interno.

EOF
)"
```

---

### Task 7: Suite completa y dashboard local

**Files:**
- Modify: ninguno salvo arreglos que salgan de la suite
- Regenerar: `exports/dashboard_CI-VA-001_2026.html` en el data-dir (fuera de git)

**Interfaces:**
- Consumes: todas las anteriores
- Produces: suite verde; HTML regenerado con `--no-open`

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest -q`

Expected: PASS. Si algo falla (p. ej. `test_filing` no debe fallar: no pinta ids al usuario), arregla en el mismo espíritu: superficie de usuario = nombre; PK solo en SQLite.

- [ ] **Step 2: Regenerar el dashboard del expediente**

Run:

```bash
uv run aeat-hub dashboard --actividad CI-VA-001 --year 2026 --no-open
```

Expected: escribe el HTML. En la columna Rubro se lee `Hogar` / `Luz`, no `CI.GAS.HOGAR`.

- [ ] **Step 3: Commit only if Step 1 left code or docs changes**

Si la suite forzó un arreglo:

```bash
git add -u
git commit -m "$(cat <<'EOF'
Cierra los huecos del plan de rubros de gestor.

EOF
)"
```

Si no hay cambios, no hagas commit vacío.

---

## Spec coverage

| Spec | Task |
| --- | --- |
| Nombres cortos defaults + casilla | 1 |
| Seed no pisa usuario; sí actualiza sistema | 1 |
| `casilla_clave` / Pintura→reparación | 2, 3 |
| Etiquetas Renta cortas | 2 |
| `cuenta alta` CLI, errores, sin imprimir id | 3, 4 |
| `reclasificar` por nombre | 4 |
| `cuentas` / asientos / validar sin id | 4 |
| Dashboard, filtros, chips, pop-up casilla | 5 |
| Excel `rubro` sin columna de id | 6 |
| Docs producto | 1, 4 |
| Duplicados / validado intactos | sin cambios de código; Task 7 los cubre con la suite |
| AE stubs sin rediseñar | 1 (casilla vacía), 3 (alta AE rechazada) |
