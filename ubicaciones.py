"""
Departamentos y municipios de Guatemala (códigos del INE, los mismos del DPI) para la residencia
del paciente y el mapa de vigilancia epidemiológica.

Fuente: límites administrativos de CONRED / OCHA (HDX, conjunto cod-ab-gtm), licencia CC BY-IGO.
datos/municipios_gt.json se generó a partir de ese archivo (nombres, códigos y centro de cada municipio).
Los lagos (códigos que terminan en 00) vienen en el mapa pero no son un lugar de residencia.
"""
import json
import os
import re

_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "municipios_gt.json")
with open(_RUTA, encoding="utf-8") as _f:
    _DATOS = json.load(_f)

FUENTE = _DATOS["fuente"]
DEPARTAMENTOS = dict(sorted(_DATOS["departamentos"].items()))
MUNICIPIOS = {c: m for c, m in sorted(_DATOS["municipios"].items()) if not c.endswith("00")}


def municipio(codigo):
    """{"nombre", "departamento", "lat", "lon"} del municipio, o None."""
    return MUNICIPIOS.get(str(codigo or "").strip())


def nombre_municipio(codigo):
    m = municipio(codigo)
    return m["nombre"] if m else None


def nombre_departamento(codigo):
    return DEPARTAMENTOS.get(str(codigo or "")[:2])


def desde_cui(cui):
    """Municipio donde se inscribió la persona (últimos 4 dígitos del DPI). Es el lugar de
    nacimiento o inscripción, NO donde vive: solo sirve como sugerencia."""
    cui = re.sub(r"\D", "", str(cui or ""))
    return cui[-4:] if len(cui) == 13 and cui[-4:] in MUNICIPIOS else None


def catalogo():
    return {"fuente": FUENTE,
            "departamentos": [{"codigo": c, "nombre": n} for c, n in DEPARTAMENTOS.items()],
            "municipios": [{"codigo": c, "nombre": m["nombre"], "departamento": m["departamento"]}
                           for c, m in MUNICIPIOS.items()]}
