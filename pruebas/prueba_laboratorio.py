"""
Pruebas del catálogo de laboratorio (laboratorio.py): validación e interpretación de resultados,
sin servidor ni base de datos.
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_laboratorio.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import laboratorio as L  # noqa: E402
from validacion import DatoInvalido  # noqa: E402

resultados = []


def dato(nombre, ok):
    resultados.append(bool(ok))
    print(f"{'OK ' if ok else 'FALLA'}  {nombre}")


def param(examen, clave):
    return next(p for p in L.EXAMENES[examen]["parametros"] if p["clave"] == clave)


def rechaza(p, valor):
    try:
        L.validar_valor(p, valor)
        return False
    except DatoInvalido:
        return True


GLU, HB, HDL, NIT = param("GLUCOSA", "glucosa"), param("HEMATO", "hemoglobina"), param("LIPIDOS", "hdl"), param("ORINA", "nitritos")
dato("el catálogo tiene exámenes de las 4 áreas", {e["categoria"] for e in L.EXAMENES.values()} == set(L.CATEGORIAS))
dato("cada parámetro tiene clave única dentro de su examen",
     all(len({p["clave"] for p in e["parametros"]}) == len(e["parametros"]) for e in L.EXAMENES.values()))
dato("los rangos normales caben dentro de lo posible", all(
    p["tipo"] == "opcion" or ((p["min"] is None or p["posible"][0] <= p["min"]) and (p["max"] is None or p["max"] <= p["posible"][1]))
    for e in L.EXAMENES.values() for p in e["parametros"]))
dato("glucosa 90 es normal, 126 alta, 55 baja",
     L.interpretar(GLU, 90) == "normal" and L.interpretar(GLU, 126) == "alto" and L.interpretar(GLU, 55) == "bajo")
dato("los límites del rango son normales (70 y 100)", L.interpretar(GLU, 70) == "normal" and L.interpretar(GLU, 100) == "normal")
dato("HDL solo tiene mínimo: 35 bajo, 80 normal", L.interpretar(HDL, 35) == "bajo" and L.interpretar(HDL, 80) == "normal")
dato("cualitativo: nitritos Positivo es anormal", L.interpretar(NIT, "Positivo") == "anormal" and L.interpretar(NIT, "Negativo") == "normal")
dato("sin valor no se interpreta", L.interpretar(GLU, None) is None)
dato("acepta número como texto y con coma decimal", L.validar_valor(HB, "13,25") == 13.2 and L.validar_valor(GLU, "126") == 126)
dato("rechaza un error de digitación (hemoglobina 132)", rechaza(HB, 132))
dato("rechaza texto, booleanos y listas en un número", rechaza(GLU, "alto") and rechaza(GLU, True) and rechaza(GLU, [1]))
dato("rechaza una opción que no existe", rechaza(NIT, "positivo") and rechaza(NIT, 1))
dato("texto del rango: '70 – 100 mg/dL', '≥ 40 mg/dL', '< 200 mg/dL'",
     L.referencia(GLU) == "70 – 100 mg/dL" and L.referencia(HDL) == "≥ 40 mg/dL"
     and L.referencia(param("LIPIDOS", "colesterol")) == "< 200 mg/dL")
r = L.resultados_interpretados("GLUCOSA", {"glucosa": 180})
dato("resultados interpretados traen nombre, unidad, referencia y nivel",
     r == [{"clave": "glucosa", "nombre": "Glucosa", "valor": 180, "unidad": "mg/dL", "referencia": "70 – 100 mg/dL", "nivel": "alto"}])
dato("el catálogo para la pantalla no expone los límites de lo posible", all("posible" not in p for e in L.catalogo() for p in e["parametros"]))

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
