"""
Pruebas de alertas_clinicas.py (signos fuera de rango, alergias al recetar y nombres parecidos),
sin servidor ni base de datos.
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_alertas.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from alertas_clinicas import alergias_en_conflicto, alertas_signos, parecido_nombre, terminos_alergia  # noqa: E402

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

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
