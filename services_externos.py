"""
Funciones para consumir los módulos externos del sistema (Educación, Seguridad
y Tributario) vía HTTP. Cada módulo expone su propia API con autenticación por
API key (header X-API-Key), siguiendo el mismo esquema que este módulo de
Salud usa en routes/externos.py.

Las rutas exactas de cada módulo externo son un placeholder hasta que se confirme su contrato definitivo; ajustar los paths
si difieren.
"""
import uuid
from datetime import datetime

import requests
from config import Config

TIMEOUT_SEGUNDOS = 5


def _get(base_url, path, params=None):
    """Realiza un GET autenticado contra un módulo externo y normaliza la respuesta."""
    url = f"{base_url}{path}"
    headers = {"X-API-Key": Config.MODULOS_API_KEY}
    try:
        respuesta = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_SEGUNDOS)
        respuesta.raise_for_status()
        return {"success": True, "data": respuesta.json().get("data", respuesta.json())}
    except requests.exceptions.RequestException as error:
        return {"success": False, "error": "error_conexion", "message": str(error)}


def _post(base_url, path, payload=None):
    """Realiza un POST autenticado contra un módulo externo y normaliza la respuesta."""
    url = f"{base_url}{path}"
    headers = {"X-API-Key": Config.MODULOS_API_KEY}
    try:
        respuesta = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_SEGUNDOS)
        respuesta.raise_for_status()
        return {"success": True, "data": respuesta.json().get("data", respuesta.json())}
    except requests.exceptions.RequestException as error:
        return {"success": False, "error": "error_conexion", "message": str(error)}


# ---------------------------------------------------------------------------
# Educación
# ---------------------------------------------------------------------------

def obtener_estudiante(cui):
    """Consulta si un CUI corresponde a un estudiante activo y su información básica."""
    return _get(Config.URL_EDUCACION, f"/api/v1/educacion/estudiantes/{cui}")


def obtener_indicadores_educacion():
    """Consulta los indicadores generales del módulo de Educación."""
    return _get(Config.URL_EDUCACION, "/api/v1/educacion/indicadores")


def coordinar_jornada(tipo_jornada, lugar, fecha, hora):
    """WS-SALUD-01: coordina con Educación una jornada de vacunación y obtiene
    la lista de estudiantes convocados (nombre, CUI, establecimiento, grado/sección, jornada)."""
    payload = {
        "tipo_jornada": tipo_jornada,
        "lugar": lugar,
        "fecha": fecha,
        "hora": hora,
    }
    return _post(Config.URL_EDUCACION, "/api/v1/educacion/jornadas/coordinar", payload)


def validar_practicante(cui):
    """WS-SALUD-07: valida ante Educación si un CUI/DPI corresponde a un
    practicante de medicina activo (universidad, carrera, semestre/nivel)."""
    return _get(Config.URL_EDUCACION, f"/api/v1/educacion/practicantes/validar/{cui}")


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def obtener_alertas_seguridad(zona=None):
    """Consulta alertas de seguridad activas, opcionalmente filtradas por zona."""
    params = {"zona": zona} if zona else None
    return _get(Config.URL_SEGURIDAD, "/api/v1/seguridad/alertas", params=params)


def obtener_indicadores_seguridad():
    """Consulta los indicadores generales del módulo de Seguridad."""
    return _get(Config.URL_SEGURIDAD, "/api/v1/seguridad/indicadores")


def consultar_antecedentes_seguridad(cui):
    """WS-SALUD-08: consulta a Seguridad si una persona (CUI/DPI) tiene
    antecedentes, tipo, nivel de riesgo y si requiere custodia."""
    return _get(Config.URL_SEGURIDAD, f"/api/v1/seguridad/ciudadanos/antecedentes/{cui}")


# ---------------------------------------------------------------------------
# Tributario
# ---------------------------------------------------------------------------

def obtener_estado_tributario(cui):
    """Consulta el estado de cumplimiento tributario de un contribuyente por CUI."""
    return _get(Config.URL_TRIBUTARIO, f"/api/v1/tributario/contribuyentes/{cui}")


def obtener_indicadores_tributario():
    """Consulta los indicadores generales del módulo Tributario."""
    return _get(Config.URL_TRIBUTARIO, "/api/v1/tributario/indicadores")


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
    return _post(Config.URL_TRIBUTARIO, "/api/v1/tributario/pagos/verificar", payload)
