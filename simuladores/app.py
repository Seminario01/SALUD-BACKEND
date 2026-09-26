"""
SIMULADORES de Educación, Seguridad y Tributario — SOLO PARA DESARROLLO.

Imitan los servicios que Salud consume, con las rutas y campos acordados con
cada equipo, para poder probar la integración mientras los otros módulos no
tienen sus URLs. Todas las respuestas llevan "simulado": true.
Cuando un equipo tenga su servicio real, solo se cambia su URL en el .env.

Uso (desde SALUD-BACKEND, con el venv activado):
    python simuladores/app.py            -> http://localhost:5055

y en el .env del backend:
    URL_EDUCACION=http://localhost:5055
    URL_SEGURIDAD=http://localhost:5055
    URL_TRIBUTARIO=http://localhost:5055

Reglas de los datos simulados (para poder demostrar cada caso):
  Seguridad  - CUI que termina en 9: antecedentes de riesgo ALTO, requiere custodia
             - CUI que termina en 7: antecedentes de riesgo BAJO
             - cualquier otro: sin antecedentes
  Educación  - CUI que termina en número PAR: es estudiante
             - CUI que termina en número impar: no es estudiante (404)
  Tributario - monto mayor a 0: pago CONFIRMADO
"""
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.before_request
def exigir_api_key():
    # Igual que los módulos reales: sin X-API-Key no se atiende
    if not request.headers.get("X-API-Key"):
        return jsonify(success=False, error="sin_api_key", simulado=True), 401


def ok(data, status=200):
    return jsonify(success=True, data={**data, "simulado": True}), status


# ----------------------------- Seguridad -----------------------------
@app.get("/api/v1/seguridad/ciudadanos/antecedentes/<cui>")
def antecedentes(cui):
    if cui.endswith("9"):
        return ok({"cui": cui, "tieneAntecedentes": True, "tipoAntecedente": "Robo agravado",
                   "nivelRiesgo": "ALTO", "requiereCustodia": True})
    if cui.endswith("7"):
        return ok({"cui": cui, "tieneAntecedentes": True, "tipoAntecedente": "Falta menor",
                   "nivelRiesgo": "BAJO", "requiereCustodia": False})
    return ok({"cui": cui, "tieneAntecedentes": False, "tipoAntecedente": None,
               "nivelRiesgo": "NINGUNO", "requiereCustodia": False})


@app.get("/api/v1/seguridad/indicadores")
def indicadores_seguridad():
    return ok({"modulo": "seguridad"})


# ----------------------------- Educación -----------------------------
@app.get("/api/v1/educacion/estudiantes/<cui>")
def estudiante(cui):
    if cui[-1:].isdigit() and int(cui[-1]) % 2 == 0:
        return ok({"cui": cui, "establecimiento": "INEB Jornada Matutina, Antigua Guatemala",
                   "grado": "3ro. Básico", "seccion": "A", "jornada": "Matutina"})
    return jsonify(success=False, error="no_encontrado", simulado=True), 404


@app.get("/api/v1/educacion/indicadores")
def indicadores_educacion():
    return ok({"modulo": "educacion"})


# ----------------------------- Tributario -----------------------------
@app.post("/api/v1/tributario/pagos/verificar")
def verificar_pago():
    datos = request.get_json(silent=True) or {}
    confirmado = float(datos.get("monto") or 0) > 0
    return ok({"numero_referencia": datos.get("numero_referencia"),
               "estado": "CONFIRMADO" if confirmado else "RECHAZADO",
               "pagoConfirmado": confirmado})


@app.get("/api/v1/tributario/indicadores")
def indicadores_tributario():
    return ok({"modulo": "tributario"})


if __name__ == "__main__":
    print(" * SIMULADORES de Educación, Seguridad y Tributario (solo desarrollo)")
    app.run(port=5055)
