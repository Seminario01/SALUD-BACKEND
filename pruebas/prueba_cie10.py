"""
Pruebas del catálogo CIE-10 (cie10.py), sin servidor ni base de datos.
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_cie10.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cie10  # noqa: E402

resultados = []


def dato(nombre, ok):
    resultados.append(bool(ok))
    print(f"{'OK ' if ok else 'FALLA'}  {nombre}")


def codigos(q, n=5):
    return [x["codigo"] for x in cie10.buscar(q, n)]


dato("el catálogo tiene más de 200 diagnósticos frecuentes", len(cie10.CATALOGO) > 200)
dato("todos los códigos tienen el formato de la CIE-10 (letra, 2 dígitos y decimales)",
     all(cie10.FORMATO.match(c) for c, _ in cie10.CATALOGO))
dato("todos los códigos caen en un capítulo", all(cie10.capitulo(c) for c, _ in cie10.CATALOGO))
dato("busca por código exacto (I10)", codigos("I10")[:1] == ["I10"])
dato("busca por inicio del código (J0 -> J00, J01.9...)", codigos("J0")[:2] == ["J00", "J01.9"])
dato("código en minúsculas y con espacios", codigos(" e11.9 ") == ["E11.9"])
dato("código sin el punto (E119)", "E11.9" in codigos("E119"))
dato("por palabras en cualquier orden (arterial hipertension)", "I10" in codigos("arterial hipertension"))
dato("sin tildes ni mayúsculas (NEUMONIA)", "J18.9" in codigos("NEUMONIA"))
dato("por el nombre común (gripe, ivu, presión alta)", "J00" in codigos("gripe") and "N39.0" in codigos("ivu")
     and codigos("presion alta")[:1] == ["I10"])
dato("palabras a medias (diab tipo 2)", "E11.9" in codigos("diab tipo 2"))
dato("algo que no existe: nada", cie10.buscar("zzzz") == [] and cie10.buscar("") == [])
dato("respeta el límite", len(cie10.buscar("a", 3)) == 3)
dato("descripción de un código", cie10.descripcion("j00").startswith("Rinofaringitis") and cie10.descripcion("X99.9") is None)
dato("trae el capítulo", cie10.buscar("I10")[0]["capitulo"] == "Circulatorio")

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
