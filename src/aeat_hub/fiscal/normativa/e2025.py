"""Ejercicio 2025. Verificado el 14 oct 2026 contra la sede de la AEAT."""

from aeat_hub.fiscal.normativa import Casillas303, D, Normativa

CASILLAS_303 = Casillas303(
    devengado={
        D("4"): ("01", "02", "03"),
        D("10"): ("04", "05", "06"),
        D("21"): ("07", "08", "09"),
        D("0"): ("150", "151", "152"),
    },
    recargo={
        D("1.75"): ("156", "157", "158"),
        D("0.5"): ("168", "169", "170"),
        D("1.4"): ("19", "20", "21"),
        D("5.2"): ("22", "23", "24"),
    },
)

NORMATIVA = Normativa(
    ejercicio=2025,
    verificado=True,
    fuentes=(
        "AEAT, instrucciones modelo 303 (2025-2026): casillas 01-09, 150-152, 156-158, 168-170, 19-24.",
        "AEAT, instrucciones modelo 130: casillas 01-19 y minoración de la casilla 13.",
        "AEAT, Manual Renta: provisiones y gastos de difícil justificación 5 %, límite 2.000 €.",
    ),
    tipos_iva=(D("21"), D("10"), D("4"), D("0")),
    tipos_recargo={D("21"): D("5.2"), D("10"): D("1.4"), D("4"): D("0.5"), D("0"): D("0")},
    casillas_303=CASILLAS_303,
    umbral_bien_inversion=D("3005.06"),
    presuncion_vehiculo_iva=D("50"),
    pago_fraccionado_130=D("20"),
    minoracion_130=(
        (D("9000"), D("100")),
        (D("10000"), D("75")),
        (D("11000"), D("50")),
        (D("12000"), D("25")),
    ),
    dificil_justificacion_pct=D("5"),
    dificil_justificacion_limite=D("2000"),
    suministros_vivienda_pct=D("30"),
    manutencion_espana=D("26.67"),
    manutencion_extranjero=D("48.08"),
    umbral_347=D("3005.06"),
    retencion_profesional=D("15"),
    retencion_profesional_inicio=D("7"),
    retencion_arrendamiento=D("19"),
)
