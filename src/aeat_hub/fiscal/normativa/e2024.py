"""Ejercicio 2024: tipos coyunturales del 5 % y 2 % (RDL 20/2022 y 4/2024)."""

from dataclasses import replace

from aeat_hub.fiscal.normativa import Casillas303, D, e2025

NORMATIVA = replace(
    e2025.NORMATIVA,
    ejercicio=2024,
    tipos_iva=(D("21"), D("10"), D("5"), D("4"), D("2"), D("0")),
    tipos_recargo={
        D("21"): D("5.2"),
        D("10"): D("1.4"),
        D("5"): D("0.62"),
        D("4"): D("0.5"),
        D("2"): D("0.26"),
        D("0"): D("0"),
    },
    casillas_303=Casillas303(
        devengado={
            **e2025.CASILLAS_303.devengado,
            D("5"): ("153", "154", "155"),
            D("2"): ("165", "166", "167"),
        },
        # El recargo de los tipos coyunturales (0,62 % y 0,26 %) no está
        # verificado: queda sin casilla y el borrador lo avisa.
        recargo=dict(e2025.CASILLAS_303.recargo),
    ),
    fuentes=("AEAT, instrucciones modelo 303 2024: 5 % en 153-155 y 2 % en 165-167.",),
    avisos=("Recargo de equivalencia de los tipos coyunturales (0,62 % y 0,26 %) sin casilla verificada.",),
)
