"""
Funciones para consumir los módulos externos del sistema (Educación, Seguridad
y Tributario) vía HTTP. Cada módulo expone su propia API con autenticación por
API key (header X-API-Key), siguiendo el mismo esquema que este módulo de
Salud usa en routes/externos.py.

Las rutas exactas de cada módulo externo son un placeholder hasta que se confirme su contrato definitivo; ajustar los paths
si difieren.
"""
import time
import uuid
from datetime import datetime

import requests
from flask import has_request_context, request

from bitacora import registrar as registrar_bitacora, resumir
from config import Config

TIMEOUT_SEGUNDOS = 3


def _headers():
    """Cabeceras para llamar a otro módulo.

    - X-API-Key: el acuerdo entre equipos para comunicación servidor a servidor.
    - Authorization: si la petición viene de un usuario, se REENVÍA su access
      token (guía del Login Único, sección 7: todos comparten aud=rsd-api).
    """
    headers = {"X-API-Key": Config.MODULOS_API_KEY}
    if has_request_context():
        token = request.headers.get("Authorization", "")
        if token.startswith("Bearer "):
            headers["Authorization"] = token
    return headers


def _modulo_de(path):
    for prefijo, nombre in (("/api/v1/educacion", "Educación"), ("/api/v1/seguridad", "Seguridad"),
                            ("/api/v1/tributario", "Tributario")):
        if path.startswith(prefijo):
            return nombre
    return "Otro"


def _llamar(metodo, base_url, path, operacion=None, registrar=True, timeout=TIMEOUT_SEGUNDOS, **kwargs):
    """Llama a un módulo externo y normaliza el resultado:
       {"success": True, "data": ..., "simulado": bool}
       {"success": False, "error": <codigo>, "message": ...} con codigo en:
         no_configurado, modulo_no_disponible, no_encontrado, respuesta_invalida
    Cada llamada queda en la bitácora de integraciones (salvo registrar=False,
    que se usa para las verificaciones de conexión del panel).
    """
    if not base_url:
        return {"success": False, "error": "no_configurado",
                "message": "La URL del módulo no está configurada en el .env"}

    inicio = time.perf_counter()
    estado_http, simulado, detalle = None, False, None
    try:
        respuesta = requests.request(metodo, f"{base_url.rstrip('/')}{path}", headers=_headers(),
                                     timeout=timeout, **kwargs)
        estado_http = respuesta.status_code
        resultado = _interpretar(respuesta)
        if not resultado["success"]:
            try:
                cuerpo = respuesta.json()
                simulado = bool(isinstance(cuerpo, dict) and cuerpo.get("simulado"))
            except ValueError:
                pass
    except requests.exceptions.RequestException as error:
        resultado = {"success": False, "error": "modulo_no_disponible",
                     "message": f"No se pudo conectar ({error.__class__.__name__})"}

    if resultado["success"]:
        simulado = resultado.get("simulado", False)
        detalle = resumir(resultado["data"])
    else:
        detalle = resultado.get("message")
    if registrar:
        registrar_bitacora("saliente", _modulo_de(path), operacion or path, metodo, path, estado_http,
                           "ok" if resultado["success"] else resultado["error"],
                           round((time.perf_counter() - inicio) * 1000), simulado, detalle)
    return resultado


def _interpretar(respuesta):
    if respuesta.status_code == 404:
        return {"success": False, "error": "no_encontrado", "message": "El módulo no encontró el dato solicitado"}
    if respuesta.status_code >= 500:
        return {"success": False, "error": "modulo_no_disponible",
                "message": f"El módulo respondió con error {respuesta.status_code}"}
    if respuesta.status_code >= 400:
        return {"success": False, "error": "respuesta_invalida",
                "message": f"El módulo rechazó la petición ({respuesta.status_code})"}
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return {"success": False, "error": "respuesta_invalida", "message": "La respuesta no es JSON"}
    datos = cuerpo.get("data", cuerpo) if isinstance(cuerpo, dict) else cuerpo
    simulado = bool(isinstance(cuerpo, dict) and cuerpo.get("simulado")) or \
        bool(isinstance(datos, dict) and datos.get("simulado"))
    return {"success": True, "data": datos, "simulado": simulado}


def _get(base_url, path, params=None, **kwargs):
    return _llamar("GET", base_url, path, params=params, **kwargs)


def _post(base_url, path, payload=None, **kwargs):
    return _llamar("POST", base_url, path, json=payload, **kwargs)


# ---------------------------------------------------------------------------
# Educación
# ---------------------------------------------------------------------------

def obtener_estudiante(cui):
    """Consulta si un CUI corresponde a un estudiante activo y su información básica."""
    return _get(Config.URL_EDUCACION, f"/api/v1/educacion/estudiantes/{cui}", operacion="Consultar estudiante")


def obtener_indicadores_educacion(**kwargs):
    """Consulta los indicadores generales del módulo de Educación."""
    return _get(Config.URL_EDUCACION, "/api/v1/educacion/indicadores", **kwargs)


def coordinar_jornada(tipo_jornada, lugar, fecha, hora):
    """WS-SALUD-01: coordina con Educación una jornada de vacunación y obtiene
    la lista de estudiantes convocados (nombre, CUI, establecimiento, grado/sección, jornada)."""
    payload = {
        "tipo_jornada": tipo_jornada,
        "lugar": lugar,
        "fecha": fecha,
        "hora": hora,
    }
    return _post(Config.URL_EDUCACION, "/api/v1/educacion/jornadas/coordinar", payload,
                 operacion="Coordinar jornada de vacunación (WS-SALUD-01)")


def validar_practicante(cui):
    """WS-SALUD-07: valida ante Educación si un CUI/DPI corresponde a un
    practicante de medicina activo (universidad, carrera, semestre/nivel)."""
    return _get(Config.URL_EDUCACION, f"/api/v1/educacion/practicantes/validar/{cui}",
                operacion="Validar practicante (WS-SALUD-07)")


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def obtener_alertas_seguridad(zona=None):
    """Consulta alertas de seguridad activas, opcionalmente filtradas por zona."""
    params = {"zona": zona} if zona else None
    return _get(Config.URL_SEGURIDAD, "/api/v1/seguridad/alertas", params=params, operacion="Consultar alertas")


def obtener_indicadores_seguridad(**kwargs):
    """Consulta los indicadores generales del módulo de Seguridad."""
    return _get(Config.URL_SEGURIDAD, "/api/v1/seguridad/indicadores", **kwargs)


def consultar_antecedentes_seguridad(cui, nombre_completo=None):
    """WS-SALUD-08: consulta a Seguridad si una persona (CUI/DPI) tiene
    antecedentes, tipo, nivel de riesgo y si requiere custodia.
    Acordado: Salud envía CUI y nombre completo; Seguridad responde
    tieneAntecedentes, tipoAntecedente, nivelRiesgo, requiereCustodia."""
    params = {"nombreCompleto": nombre_completo} if nombre_completo else None
    return _get(Config.URL_SEGURIDAD, f"/api/v1/seguridad/ciudadanos/antecedentes/{cui}", params=params,
                operacion="Consultar antecedentes (WS-SALUD-08)")


# ---------------------------------------------------------------------------
# Tributario
# ---------------------------------------------------------------------------

def obtener_estado_tributario(cui):
    """Consulta el estado de cumplimiento tributario de un contribuyente por CUI."""
    return _get(Config.URL_TRIBUTARIO, f"/api/v1/tributario/contribuyentes/{cui}", operacion="Estado tributario")


def obtener_indicadores_tributario(**kwargs):
    """Consulta los indicadores generales del módulo Tributario."""
    return _get(Config.URL_TRIBUTARIO, "/api/v1/tributario/indicadores", **kwargs)


def generar_numero_referencia_pago():
    """Genera el numero_referencia que Salud debe emitir (correlativo propio,
    no lo genera Tributario) antes de solicitar la verificación de un pago."""
    correlativo = uuid.uuid4().hex[:8].upper()
    return f"SALUD-{datetime.utcnow().year}-{correlativo}"


def verificar_pago_tributario(numero_referencia, dpi, concepto, monto, estado_pago):
    """WS-SALUD-09: envía a Tributario la verificación de un pago (el
    numero_referencia lo genera Salud, ver generar_numero_referencia_pago)."""
    payload = {
        "numero_referencia": numero_referencia,
        "dpi": dpi,
        "concepto": concepto,
        "monto": monto,
        "estado_pago": estado_pago,
    }
    return _post(Config.URL_TRIBUTARIO, "/api/v1/tributario/pagos/verificar", payload,
                 operacion="Verificar pago (WS-SALUD-09)")


# ---------------------------------------------------------------------------
# Simuladores: pedirle a un módulo simulado que consuma un servicio de Salud
# ---------------------------------------------------------------------------

def disparar_caso_simulado(base_url, caso, cuerpo=None):
    """Solo funciona contra los simuladores (simuladores/app.py)."""
    return _post(base_url, f"/simulador/disparar/{caso}", cuerpo or {}, registrar=False, timeout=10)
