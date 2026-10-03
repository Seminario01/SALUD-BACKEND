"""
SIMULADORES de Educación, Seguridad y Tributario.

Imitan, según el contrato acordado (docs/CONTRATOS.md), los servicios que
Salud consume de los otros módulos. Sirven para demostrar que Salud está
listo para integrarse mientras los otros equipos publican sus servicios.
TODAS las respuestas llevan "simulado": true y la interfaz de Salud lo
muestra. Cuando un equipo tenga su servicio real, solo se cambia su URL
en el .env del backend; el código de Salud no cambia.

Los datos (simuladores/datos.py) son ficticios y coherentes con los
pacientes de demostración de SALUD-DATABASE/datos_demo.sql.

También pueden hacer de "otro módulo" que CONSUME a Salud
(POST /simulador/disparar/<caso>), para mostrar la integración en las dos
direcciones.

Uso local (desde SALUD-BACKEND, con el venv activado):
    python simuladores/app.py                 -> http://localhost:5055
En Docker lo levanta deploy/docker-compose.yml (servicio "simuladores").

Para un CUI que no está en el padrón (pacientes nuevos) se usan reglas:
  Seguridad  - termina en 9: riesgo ALTO (custodia); en 7: riesgo BAJO
  Educación  - termina en número par: estudiante
  Tributario - monto > 0: pago CONFIRMADO; CUI que termina en 3: pago no registrado
"""
import hashlib
import os
import sys
import time
from collections import deque
from datetime import date, datetime, timedelta

import requests
from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos  # noqa: E402

app = Flask(__name__)
app.json.ensure_ascii = False

API_KEY = os.getenv("MODULOS_API_KEY", "")          # si está definida, se exige igual
SALUD_URL = os.getenv("SALUD_URL", "http://127.0.0.1:5050").rstrip("/")
REGISTRO = deque(maxlen=200)                         # últimas peticiones recibidas

MODULO_POR_RUTA = {"/api/v1/seguridad": "Seguridad", "/api/v1/educacion": "Educación",
                   "/api/v1/tributario": "Tributario", "/simulador": "Simulador"}


def _modulo(ruta):
    return next((m for p, m in MODULO_POR_RUTA.items() if ruta.startswith(p)), "Simulador")


@app.before_request
def exigir_api_key():
    request._inicio = time.perf_counter()
    clave = request.headers.get("X-API-Key")
    if not clave:
        return jsonify(success=False, error="sin_api_key", message="Falta X-API-Key", simulado=True), 401
    if API_KEY and clave != API_KEY:
        return jsonify(success=False, error="api_key_invalida", message="API key inválida", simulado=True), 403


@app.after_request
def registrar(respuesta):
    if not request.path.startswith("/simulador/registro"):
        REGISTRO.appendleft({
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "modulo": _modulo(request.path), "metodo": request.method, "ruta": request.full_path.rstrip("?"),
            "status": respuesta.status_code,
            "conToken": request.headers.get("Authorization", "").startswith("Bearer "),
            "duracionMs": round((time.perf_counter() - getattr(request, "_inicio", time.perf_counter())) * 1000),
        })
    return respuesta


def ok(data, status=200):
    if isinstance(data, dict):
        data = {**data, "simulado": True}
    return jsonify(success=True, data=data, simulado=True), status


def no_encontrado(mensaje):
    return jsonify(success=False, error="no_encontrado", message=mensaje, simulado=True), 404


def _ultimo_digito(cui):
    return int(cui[-1]) if cui[-1:].isdigit() else 1


# ============================== Seguridad ==============================
@app.get("/api/v1/seguridad/ciudadanos/antecedentes/<cui>")
def antecedentes(cui):
    """WS-SALUD-08: Salud envía CUI y nombre; Seguridad responde antecedentes."""
    nombre = request.args.get("nombreCompleto") or datos.NOMBRES.get(cui)
    if cui in datos.ANTECEDENTES:
        return ok({"cui": cui, **datos.ANTECEDENTES[cui]})
    if cui not in datos.NOMBRES:                     # CUI fuera del padrón: reglas
        d = _ultimo_digito(cui)
        if d == 9:
            return ok({"cui": cui, "nombreCompleto": nombre, "tieneAntecedentes": True,
                       "tipoAntecedente": "Robo agravado", "nivelRiesgo": "ALTO", "requiereCustodia": True,
                       "detalle": "Registro de prueba (regla del simulador)."})
        if d == 7:
            return ok({"cui": cui, "nombreCompleto": nombre, "tieneAntecedentes": True,
                       "tipoAntecedente": "Falta menor", "nivelRiesgo": "BAJO", "requiereCustodia": False,
                       "detalle": "Registro de prueba (regla del simulador)."})
    return ok({"cui": cui, "nombreCompleto": nombre, "tieneAntecedentes": False, "tipoAntecedente": None,
               "nivelRiesgo": "NINGUNO", "requiereCustodia": False})


@app.get("/api/v1/seguridad/alertas")
def alertas():
    zona = (request.args.get("zona") or "").lower()
    lista = [a for a in datos.ALERTAS if not zona or zona in a["zona"].lower() or zona in a["departamento"].lower()]
    return ok(lista)


@app.get("/api/v1/seguridad/indicadores")
def indicadores_seguridad():
    return ok({"modulo": "seguridad", **datos.INDICADORES_SEGURIDAD})


# ============================== Educación ==============================
@app.get("/api/v1/educacion/estudiantes/<cui>")
def estudiante(cui):
    if cui in datos.ESTUDIANTES:
        return ok({"cui": cui, "estado": "INSCRITO", "cicloEscolar": 2026, **datos.ESTUDIANTES[cui]})
    if cui not in datos.NOMBRES and _ultimo_digito(cui) % 2 == 0:
        return ok({"cui": cui, "estado": "INSCRITO", "cicloEscolar": 2026, "nivel": "Básico",
                   "establecimiento": "INEB Jornada Matutina, Antigua Guatemala", "grado": "2do. Básico",
                   "seccion": "A", "jornada": "Matutina", "detalle": "Registro de prueba (regla del simulador)."})
    return no_encontrado("El CUI no corresponde a un estudiante inscrito en el ciclo 2026")


@app.post("/api/v1/educacion/jornadas/coordinar")
def coordinar_jornada():
    """WS-SALUD-01: devuelve los estudiantes convocados a la jornada."""
    cuerpo = request.get_json(silent=True) or {}
    lugar = (cuerpo.get("lugar") or "").lower()
    convocados = [
        {"cui": cui, "nombreCompleto": e["nombreCompleto"], "establecimiento": e["establecimiento"],
         "grado": e["grado"], "seccion": e["seccion"], "jornada": e["jornada"]}
        for cui, e in datos.ESTUDIANTES.items()
        if e["nivel"] != "Universitario" and (not lugar or lugar in e["establecimiento"].lower())
    ]
    if not convocados:          # el lugar no coincide con un establecimiento: todos los de básico y diversificado
        convocados = [{"cui": cui, "nombreCompleto": e["nombreCompleto"], "establecimiento": e["establecimiento"],
                       "grado": e["grado"], "seccion": e["seccion"], "jornada": e["jornada"]}
                      for cui, e in datos.ESTUDIANTES.items() if e["nivel"] != "Universitario"]
    return ok(convocados)


@app.get("/api/v1/educacion/practicantes/validar/<cui>")
def validar_practicante(cui):
    """WS-SALUD-07"""
    if cui in datos.PRACTICANTES:
        return ok({"cui": cui, "esPracticante": True, **datos.PRACTICANTES[cui]})
    return no_encontrado("El CUI no corresponde a un practicante activo")


@app.get("/api/v1/educacion/indicadores")
def indicadores_educacion():
    return ok({"modulo": "educacion", **datos.INDICADORES_EDUCACION})


# ============================== Tributario ==============================
def _autorizacion(texto):
    return "AUT-" + hashlib.sha1(texto.encode()).hexdigest()[:10].upper()


@app.post("/api/v1/tributario/pagos/verificar")
def verificar_pago():
    """WS-SALUD-09: Salud envía numero_referencia, dpi, concepto, monto y estado_pago."""
    cuerpo = request.get_json(silent=True) or {}
    referencia = cuerpo.get("numero_referencia")
    dpi = str(cuerpo.get("dpi") or "")
    try:
        monto = float(cuerpo.get("monto") or 0)
    except (TypeError, ValueError):
        monto = 0
    faltan = [c for c in ("numero_referencia", "dpi", "concepto", "monto") if not cuerpo.get(c)]
    if faltan:
        return jsonify(success=False, error="datos_incompletos", message=f"Faltan: {', '.join(faltan)}",
                       simulado=True), 400

    no_registrado = dpi in datos.PAGO_NO_REGISTRADO or (dpi not in datos.NOMBRES and dpi.endswith("3"))
    if monto <= 0 or no_registrado:
        return ok({"numero_referencia": referencia, "dpi": dpi, "estado": "PENDIENTE", "pagoConfirmado": False,
                   "mensaje": "No se encontró un pago registrado con esos datos. El paciente puede pagar en agencia o en línea."})
    return ok({"numero_referencia": referencia, "dpi": dpi, "nombreContribuyente": datos.NOMBRES.get(dpi),
               "concepto": cuerpo.get("concepto"), "montoRegistrado": round(monto, 2), "moneda": "GTQ",
               "estado": "CONFIRMADO", "pagoConfirmado": True, "numeroAutorizacion": _autorizacion(referencia or dpi),
               "fechaPago": (datetime.now() - timedelta(hours=2)).isoformat(timespec="minutes"),
               "canal": "Agencia bancaria"})


@app.get("/api/v1/tributario/contribuyentes/<cui>")
def contribuyente(cui):
    if cui not in datos.NOMBRES:
        return no_encontrado("Contribuyente no registrado")
    solvente = cui not in datos.CONTRIBUYENTES_INSOLVENTES
    return ok({"cui": cui, "nombreContribuyente": datos.NOMBRES[cui], "solvente": solvente,
               "estado": "SOLVENTE" if solvente else "CON_SALDO_PENDIENTE",
               "saldoPendiente": 0 if solvente else 1240.50})


@app.get("/api/v1/tributario/indicadores")
def indicadores_tributario():
    return ok({"modulo": "tributario", **datos.INDICADORES_TRIBUTARIO})


# ======================= El simulador consume a Salud =======================
def _casos(cuerpo):
    en_una_semana = (date.today() + timedelta(days=7)).isoformat()
    return {
        "seguridad-establecimientos": ("Seguridad", "GET",
            "/api/v1/salud/establecimientos/disponibilidad?departamento=Sacatepéquez&tipoAtencion=EMERGENCIA", None,
            "Alerta ALR-2026-0912 (accidente en RN-10): ¿qué establecimientos atienden emergencias?"),
        "educacion-jornada": ("Educación", "POST", "/api/v1/salud/jornadas/coordinar",
            {"tipo_jornada": "Vacunación Td y VPH", "lugar": "INEB Jornada Matutina, Antigua Guatemala",
             "fecha": en_una_semana, "hora": "08:00"},
            "Educación solicita una jornada de vacunación en el INEB."),
        "educacion-practicante": ("Educación", "GET", "/api/v1/salud/practicantes/2520123450106/horas", None,
            "Educación consulta las horas de práctica de Daniela Sofía Paredes Lima."),
        "tributario-costo": ("Tributario", "GET", f"/api/v1/salud/citas/{int(cuerpo.get('cita_id') or 1)}/costo", None,
            "Tributario consulta el costo y el estado de pago de una cita."),
        "auditoria-indicadores": ("Auditoría", "GET", "/api/v1/salud/indicadores", None,
            "Auditoría Social consulta los indicadores agregados de Salud (sin datos personales)."),
    }


@app.post("/simulador/disparar/<caso>")
def disparar(caso):
    cuerpo_peticion = request.get_json(silent=True) or {}
    casos = _casos(cuerpo_peticion)
    if caso not in casos:
        return jsonify(success=False, error="no_encontrado", message=f"Casos: {', '.join(casos)}", simulado=True), 404
    origen, metodo, ruta, cuerpo, contexto = casos[caso]
    inicio = time.perf_counter()
    try:
        r = requests.request(metodo, f"{SALUD_URL}{ruta}", json=cuerpo, timeout=8, headers={
            "X-API-Key": API_KEY or request.headers.get("X-API-Key", ""),
            "X-Modulo-Origen": origen, "X-Simulado": "true"})
        try:
            respuesta = r.json()
        except ValueError:
            respuesta = r.text[:500]
        status = r.status_code
    except requests.RequestException as error:
        respuesta, status = {"error": error.__class__.__name__}, None
    return ok({"caso": caso, "origen": origen, "destino": "Salud", "contexto": contexto,
               "peticion": {"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo},
               "respuesta": {"status": status, "cuerpo": respuesta},
               "duracionMs": round((time.perf_counter() - inicio) * 1000)})


@app.get("/simulador/registro")
def ver_registro():
    return ok(list(REGISTRO))


if __name__ == "__main__":
    print(" * SIMULADORES de Educación, Seguridad y Tributario (datos ficticios)")
    app.run(host=os.getenv("SIM_HOST", "127.0.0.1"), port=int(os.getenv("SIM_PORT", "5055")))
