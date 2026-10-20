"""
Pruebas de alertas_clinicas.py (signos fuera de rango, alergias e interacciones al recetar y nombres parecidos),
sin servidor ni base de datos.
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_alertas.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from alertas_clinicas import alergias_en_conflicto, alertas_signos, interacciones, parecido_nombre, terminos_alergia  # noqa: E402

resultados = []


def dato(nombre, ok):
    resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}  {nombre}")


def signos(**kw):
    return [a["signo"] + ":" + a["nivel"] for a in alertas_signos(kw)]


# --- Signos vitales ---
dato("signos normales: sin alertas", signos(presion="120/80", temperatura=36.8, frecuencia_cardiaca=78, saturacion=97) == [])
dato("sin signos: sin alertas", signos() == [])
dato("fiebre 38.5", signos(temperatura=38.5) == ["temperatura:alto"])
dato("37.5 todavía es normal", signos(temperatura=37.5) == [])
dato("temperatura baja 35.2", signos(temperatura=35.2) == ["temperatura:bajo"])
dato("presión alta 150/95", signos(presion="150/95") == ["presion:alto"])
dato("presión alta solo por la diastólica (130/92)", signos(presion="130/92") == ["presion:alto"])
dato("presión baja 85/55", signos(presion="85/55") == ["presion:bajo"])
dato("pulso alto 120 y bajo 45", signos(frecuencia_cardiaca=120) == ["frecuencia_cardiaca:alto"]
     and signos(frecuencia_cardiaca=45) == ["frecuencia_cardiaca:bajo"])
dato("saturación 92 baja, 95 normal", signos(saturacion=92) == ["saturacion:bajo"] and signos(saturacion=95) == [])
dato("varias alertas a la vez", len(alertas_signos({"temperatura": 39, "saturacion": 90, "frecuencia_cardiaca": 130})) == 3)
dato("el texto de la alerta trae el valor", alertas_signos({"temperatura": 38.9})[0]["texto"] == "Fiebre (38.9 °C)")

# --- Alergias ---
AMOX = {"nombre": "Amoxicilina", "presentacion": "Cápsula 500 mg"}
IBU = {"nombre": "Ibuprofeno", "presentacion": "Tableta 400 mg"}
PARA = {"nombre": "Acetaminofén", "presentacion": "Tableta 500 mg", "descripcion": "Analgésico y antipirético"}
dato("penicilina choca con amoxicilina (misma familia)", alergias_en_conflicto("Penicilina", AMOX) == ["penicilina"])
dato("sin tildes ni mayúsculas: 'PENICILÍNA'", alergias_en_conflicto("PENICILÍNA", AMOX) == ["penicilina"])
dato("alergia a la ampicilina avisa con amoxicilina", alergias_en_conflicto("ampicilina", AMOX) == ["ampicilina"])
dato("'Alergia a AINES' choca con ibuprofeno", alergias_en_conflicto("Alergia a AINES", IBU) == ["aines"])
dato("aspirina choca con ibuprofeno (AINE)", alergias_en_conflicto("aspirina", IBU) == ["aspirina"])
dato("penicilina NO choca con acetaminofén", alergias_en_conflicto("Penicilina, sulfas", PARA) == [])
dato("varias alergias, solo avisa la que choca", alergias_en_conflicto("látex; penicilina y polvo", AMOX) == ["penicilina"])
dato("'Niega alergias' no cuenta como alergia", terminos_alergia("Niega alergias") == [] and terminos_alergia("Ninguna") == [])
dato("sin alergias registradas: nada", alergias_en_conflicto(None, AMOX) == [] and alergias_en_conflicto("", AMOX) == [])
dato("el nombre del medicamento en la alergia (texto libre)", alergias_en_conflicto("ibuprofeno", IBU) == ["ibuprofeno"])
dato("no confunde partes de palabras ('sal' no es 'salbutamol')",
     alergias_en_conflicto("sal", {"nombre": "Salbutamol"}) == [])
dato("sulfas choca con trimetoprim-sulfametoxazol",
     alergias_en_conflicto("Sulfas", {"nombre": "Trimetoprim-Sulfametoxazol"}) == ["sulfas"])

# --- Nombres parecidos (paciente duplicado) ---
dato("mismo nombre con distinta tilde y mayúsculas", parecido_nombre("María García", "maria garcia") == 1.0)
dato("nombre corto contenido en el completo", parecido_nombre("María García", "María José García López") >= 0.85)
dato("palabras en otro orden", parecido_nombre("García López María", "María García López") >= 0.85)
dato("un error de letra", parecido_nombre("Jose Perez Lopez", "Jose Peres Lopez") >= 0.85)
dato("nombres distintos no se parecen", parecido_nombre("María García", "Pedro Ramírez") < 0.6)
dato("un solo nombre en común no basta", parecido_nombre("María García", "María") < 0.85)


# --- Interacciones entre medicamentos ---
def pares(nuevos, activos=()):
    return [(h["medicamento"], h["con"], h["severidad"]) for h in interacciones(nuevos, activos)]


dato("acetaminofén + amoxicilina: sin interacción", interacciones(["Acetaminofén", "Amoxicilina"]) == [])
dato("ibuprofeno + naproxeno: duplicidad de AINE", pares(["Ibuprofeno", "Naproxeno"]) == [("Ibuprofeno", "Naproxeno", "moderada")]
     and "Duplicidad" in interacciones(["Ibuprofeno", "Naproxeno"])[0]["texto"])
dato("warfarina + ibuprofeno: grave (sangrado)", pares(["Warfarina", "Ibuprofeno"]) == [("Warfarina", "Ibuprofeno", "grave")])
dato("con un medicamento de otra receta activa", pares(["Ibuprofeno"], [("Losartán", "receta #3")]) == [("Ibuprofeno", "Losartán", "moderada")]
     and interacciones(["Ibuprofeno"], [("Losartán", "receta #3")])[0]["origen"] == "receta #3")
dato("enalapril + espironolactona: grave (potasio alto)", pares(["Enalapril"], [("Espironolactona", "x")])[0][2] == "grave")
dato("ciprofloxacina + sulfato ferroso: separar tomas", "horas" in interacciones(["Ciprofloxacina"], [("Sulfato ferroso", "x")])[0]["texto"])
dato("simvastatina + azitromicina: no avisa (solo claritro/eritro)", interacciones(["Simvastatina", "Azitromicina"]) == []
     and pares(["Simvastatina", "Claritromicina"])[0][2] == "grave")
dato("losartán potásico no se confunde con potasio", interacciones(["Losartán potásico", "Enalapril"])[0]["texto"].startswith("Doble"))
dato("el mismo medicamento en otra receta no es interacción", interacciones(["Ibuprofeno"], [("Ibuprofeno", "receta #9")]) == [])
dato("aspirina + ibuprofeno: un solo aviso", len(interacciones(["Aspirina", "Ibuprofeno"])) == 1)
dato("primero las graves", [h["severidad"] for h in interacciones(["Ibuprofeno", "Enalapril", "Warfarina"])][0] == "grave")
dato("nombres con tildes y mayúsculas (TRAMADOL + Sertralina)", pares(["TRAMADOL", "Sertralina"])[0][2] == "grave")

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
