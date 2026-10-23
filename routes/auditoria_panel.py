"""
Panel "Auditoría Social" de la pantalla Integraciones (permiso integraciones.ver).

  GET  /integraciones/auditoria          lista de comprobación, última consulta exitosa, rechazos y motivos
  POST /integraciones/auditoria/probar   hace ahora mismo las consultas que haría Auditoría y dice si responden

Sirve para demostrar que los servicios para Auditoría están listos y, si su tablero no recibe datos,
saber por qué (cada intento queda en la bitácora de integraciones, ver auditoria_registro.py).
"""
from collections import Counter
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify

from auditoria_registro import CABECERA_PRUEBA
from auth import ROL_AUDITORIA_LECTURA, ROLES_AUDITORIA, get_jwk_client, requiere_permiso, validar_token
from config import Config
from models import BitacoraIntegracion
from routes.auditoria import RUTA as RUTA_TABLERO, RUTAS_ALIAS, calcular

auditoria_panel_bp = Blueprint("auditoria_panel", __name__)
DIAS = 7

# Motivo de rechazo -> explicación en palabras y qué le falta a quien consulta
MOTIVOS = {
    "sin_credenciales": "No envió clave (X-API-Key) ni token del Login Único.",
    "sin_api_key": "No envió la clave X-API-Key.",
    "api_key_invalida": "La clave X-API-Key no es la que Salud entregó.",
    "sin_token": "No envió el token del Login Único (Authorization: Bearer ...).",
    "token_expirado": "El token ya venció: hay que pedir uno nuevo al Login Único.",
    "token_audiencia": f"El token no trae la audiencia {Config.AUTH_AUDIENCE}.",
    "token_otro_emisor": "El token es de otro Login Único (no del que usa Salud).",
    "token_firma": "La firma del token no es válida.",
    "token_mal_formado": "Lo que envió como token no es un token.",
    "token_invalido": "El token no es válido.",
    "token_incompleto": "Al token le falta un dato obligatorio.",
    "permiso_denegado": f"El usuario del token no tiene el rol {ROL_AUDITORIA_LECTURA} (o auditoria:analista / auditoria:admin).",
    "rol_insuficiente": f"El usuario del token no tiene el rol {ROL_AUDITORIA_LECTURA}.",
    "rango_invalido": "Las fechas desde/hasta faltan o no son AAAA-MM-DD.",
}


def _fila(b):
    return {"fecha": b.fecha.isoformat(), "operacion": b.operacion, "ruta": b.ruta, "estado_http": b.estado_http,
            "resultado": b.resultado, "detalle": b.detalle, "prueba": b.simulado, "usuario": b.usuario}


def _operativo():
    """El servicio para Auditoría responde: el cálculo del tablero funciona y el Login Único que firma
    su token está disponible. No hace peticiones ni deja registros."""
    try:
        hoy = date.today()
        indicadores, _ = calcular(hoy.replace(day=1), hoy)
        get_jwk_client().get_signing_keys()
        return bool(indicadores)
    except Exception:  # noqa: BLE001
        return False


@auditoria_panel_bp.route("/api/v1/salud/integraciones/auditoria", methods=["GET"])
@validar_token
@requiere_permiso("integraciones.ver")
def panel_auditoria():
    """
    Estado de los servicios para Auditoría Social
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    responses:
      200:
        description: "servicios, configuracion, ultima_exitosa, rechazos (por motivo, 7 días), intentos"
    """
    base = BitacoraIntegracion.query.filter(BitacoraIntegracion.modulo == "Auditoría", BitacoraIntegracion.direccion == "entrante")
    exitosa = base.filter(BitacoraIntegracion.resultado == "ok", BitacoraIntegracion.simulado.is_(False)) \
        .order_by(BitacoraIntegracion.fecha.desc()).first()
    desde = datetime.now() - timedelta(days=DIAS)
    recientes = base.filter(BitacoraIntegracion.fecha >= desde).order_by(BitacoraIntegracion.fecha.desc()).all()
    if not Config.SIMULACIONES:
        recientes = [b for b in recientes if not b.simulado]       # en producción, sin las pruebas del panel
    reales = [b for b in recientes if not b.simulado]
    rechazos = {}
    for b in reales:
        if b.resultado == "ok":
            continue
        r = rechazos.setdefault(b.resultado, {"motivo": b.resultado, "explicacion": MOTIVOS.get(b.resultado, "Salud rechazó la consulta."),
                                              "veces": 0, "ultimo": b.fecha.isoformat(), "ejemplo": b.detalle, "ruta": b.ruta})
        r["veces"] += 1
    por_dia = Counter(b.fecha.date().isoformat() for b in reales if b.resultado == "ok")
    return jsonify(success=True, data={
        "operativo": _operativo(),
        "servicios": [
            {"nombre": "Tablero de Auditoría (indicadores por rango)", "ruta": f"GET {RUTA_TABLERO}?desde=AAAA-MM-DD&hasta=AAAA-MM-DD",
             "alias": list(RUTAS_ALIAS), "credencial": f"Token del Login Único con el rol {ROL_AUDITORIA_LECTURA}"},
            {"nombre": "Indicadores agregados", "ruta": "GET /api/v1/salud/indicadores",
             "credencial": f"X-API-Key de Auditoría, o token con {' / '.join(ROLES_AUDITORIA)}"},
            {"nombre": "Ejecución presupuestaria", "ruta": "GET /api/v1/salud/presupuesto/ejecucion",
             "credencial": f"X-API-Key de Auditoría, o token con {' / '.join(ROLES_AUDITORIA)}"},
        ],
        "configuracion": {"login_unico": Config.AUTH_ISSUER, "audiencia": Config.AUTH_AUDIENCE, "rol_tablero": ROL_AUDITORIA_LECTURA,
                          "clave_auditoria": "Auditoría" in Config.CLAVES_ENTRADA},
        "ultima_exitosa": _fila(exitosa) if exitosa else None,
        "exitosas_7_dias": sum(por_dia.values()),
        "rechazadas_7_dias": sum(r["veces"] for r in rechazos.values()),
        "rechazos": sorted(rechazos.values(), key=lambda r: -r["veces"]),
        "intentos": [_fila(b) for b in recientes[:40]],
    }), 200


@auditoria_panel_bp.route("/api/v1/salud/integraciones/auditoria/probar", methods=["POST"])
@validar_token
@requiere_permiso("integraciones.ver")
def probar_auditoria():
    """
    Probar ahora los servicios para Auditoría Social
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Hace las consultas que haría Auditoría: los indicadores con la clave de Auditoría (si está
      configurada), el cálculo del tablero del mes y la conexión con el Login Único que valida su token.
      Quedan en la bitácora marcadas como prueba.
    responses:
      200:
        description: "pasos [{nombre, ok, texto}] y todo_bien"
    """
    pasos = []

    def paso(nombre, ok, texto):
        pasos.append({"nombre": nombre, "ok": bool(ok), "texto": texto})

    # 1. Indicadores (la misma petición que haría el servidor de Auditoría). Sin clave propia de
    #    Auditoría (es opcional: su tablero usa el token) se prueba el servicio con la clave común.
    clave = Config.CLAVES_ENTRADA.get("Auditoría") or Config.MODULOS_API_KEY
    cual = "la clave de Auditoría" if Config.CLAVES_ENTRADA.get("Auditoría") else "la clave común (Auditoría no tiene clave propia; es opcional)"
    if clave:
        r = current_app.test_client().get("/api/v1/salud/indicadores", headers={
            "X-API-Key": clave, CABECERA_PRUEBA: "1", "X-Simulado": "true",       # queda en la bitácora como prueba
            "X-Modulo-Origen": "Auditoría", "User-Agent": "Panel de Integraciones"})
        datos = (r.get_json(silent=True) or {}).get("data") or {}
        paso("Indicadores agregados", r.status_code == 200,
             f"Con {cual}: respondió {r.status_code}, {datos.get('pacientes_totales', '—')} pacientes y totales de citas, camas y farmacia, sin datos personales."
             if r.status_code == 200 else f"Con {cual}: respondió {r.status_code}.")
    else:
        paso("Indicadores agregados", True, "No hay clave de módulos configurada; Auditoría consulta con su token (paso 3).")

    # 2. El tablero: el mismo cálculo que responde a la ingeniera, para el mes en curso
    try:
        hoy = date.today()
        indicadores, series = calcular(hoy.replace(day=1), hoy)
        paso("Cálculo del tablero (mes en curso)", bool(indicadores),
             f"{len(indicadores)} indicadores y {len(series)} series listos para {RUTA_TABLERO}.")
    except Exception as error:  # noqa: BLE001
        paso("Cálculo del tablero (mes en curso)", False, f"No se pudo calcular: {error.__class__.__name__}")

    # 3. El Login Único que firma el token de Auditoría responde (sin él no se puede validar su token)
    try:
        get_jwk_client().get_signing_keys()
        paso("Login Único para validar el token", True, f"Las llaves de {Config.AUTH_ISSUER} están disponibles (audiencia {Config.AUTH_AUDIENCE}).")
    except Exception as error:  # noqa: BLE001
        paso("Login Único para validar el token", False, f"No se pudieron leer las llaves del Login Único ({error.__class__.__name__}).")

    return jsonify(success=True, data={"pasos": pasos, "todo_bien": all(p["ok"] for p in pasos)}), 200
