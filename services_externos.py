"""
Funciones para consumir los módulos externos del sistema (Educación, Seguridad
y Tributario) vía HTTP. Cada módulo expone su propia API con autenticación por
API key (header X-API-Key), siguiendo el mismo esquema que este módulo de
Salud usa en routes/externos.py.

Las rutas exactas de cada módulo externo son un placeholder hasta que se confirme su contrato definitivo; ajustar los paths
si difieren.
"""
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


# ---------------------------------------------------------------------------
# Educación
# ---------------------------------------------------------------------------

def obtener_estudiante(cui):
    """Consulta si un CUI corresponde a un estudiante activo y su información básica."""
    return _get(Config.URL_EDUCACION, f"/api/v1/educacion/estudiantes/{cui}")


def obtener_indicadores_educacion():
    """Consulta los indicadores generales del módulo de Educación."""
    return _get(Config.URL_EDUCACION, "/api/v1/educacion/indicadores")


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


# ---------------------------------------------------------------------------
# Tributario
# ---------------------------------------------------------------------------

def obtener_estado_tributario(cui):
    """Consulta el estado de cumplimiento tributario de un contribuyente por CUI."""
    return _get(Config.URL_TRIBUTARIO, f"/api/v1/tributario/contribuyentes/{cui}")


def obtener_indicadores_tributario():
    """Consulta los indicadores generales del módulo Tributario."""
    return _get(Config.URL_TRIBUTARIO, "/api/v1/tributario/indicadores")
