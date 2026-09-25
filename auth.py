"""
Autenticación y autorización del Módulo de Salud contra el Login Único (Keycloak).

Reglas del servicio transversal AUTH (ver "Cómo consumir el Login Único"):
  - El token se valida LOCALMENTE contra el JWKS del issuer. La llave pública se
    descarga una vez y queda en caché; no se consulta al servidor de identidad en
    cada petición. Si el Login Único se apaga, los tokens ya emitidos siguen
    validando hasta que expiren.
  - Se valida firma, iss, aud (rsd-api) y exp, con el algoritmo fijo RS256.
  - El usuario se identifica por el claim `sub` (nunca por el email).
  - Los roles vienen en `realm_access.roles`. No existe tabla de usuarios propia.
  - 401 = no sé quién sos (sin token, vencido, firma inválida).
    403 = sé quién sos, pero no tenés el rol o el registro no es tuyo.
"""
import logging
from functools import wraps

import jwt
from flask import request, jsonify, g
from jwt import PyJWKClient

from config import Config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Roles del Login Único que usa este módulo
# ---------------------------------------------------------------------------
ROL_MEDICO = "salud:medico"
ROL_ADMIN = "salud:admin"
# Aún no existe en el realm: hay que pedirlo a la ingeniera. Mientras no exista,
# las operaciones de recepción las hace salud:admin (nadie recibe este rol).
ROL_RECEPCION = "salud:recepcion"
ROL_CIUDADANO = "ciudadano"

# Personal del hospital: puede ver datos de cualquier paciente.
ROLES_PERSONAL = (ROL_MEDICO, ROL_ADMIN, ROL_RECEPCION)

# ---------------------------------------------------------------------------
# JWKS en caché
# ---------------------------------------------------------------------------
_jwk_client = None


def get_jwk_client():
    """Cliente JWKS único por proceso.

    cache_keys=True guarda cada llave por su `kid` para siempre (lru_cache), así
    que después de la primera descarga no vuelve a llamar al Login Único salvo
    que llegue un token firmado con una llave nueva (rotación).
    """
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(
            Config.AUTH_JWKS_URL,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=12 * 60 * 60,
            timeout=5,
        )
    return _jwk_client


def precargar_jwks():
    """Descarga las llaves al arrancar, para no depender del Login Único en la
    primera petición. Si no está disponible, solo se avisa en el log."""
    try:
        for llave in get_jwk_client().get_signing_keys():
            get_jwk_client().get_signing_key(llave.key_id)
        log.info("JWKS precargado desde %s", Config.AUTH_JWKS_URL)
    except Exception as error:  # noqa: BLE001
        log.warning("No se pudo precargar el JWKS (%s). Se intentará en la primera petición.", error)


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


# ---------------------------------------------------------------------------
# Decoradores
# ---------------------------------------------------------------------------
def validar_token(f):
    """Exige un access token válido del Login Único y deja el usuario en g.usuario."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _error(401, "sin_token", "Falta el token")

        token = auth_header.split(" ", 1)[1].strip()
        try:
            signing_key = get_jwk_client().get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError:
            # Solo pasa si llega una llave que nunca vimos y el Login Único no responde.
            return _error(503, "auth_no_disponible", "No se pudo obtener la llave del Login Único")
        except jwt.PyJWKClientError:
            return _error(401, "token_invalido", "El token está firmado con una llave desconocida")
        except jwt.InvalidTokenError:
            return _error(401, "token_invalido", "Token mal formado")

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],          # fijo: nunca dejar que el token elija
                audience=Config.AUTH_AUDIENCE,
                issuer=Config.AUTH_ISSUER,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            return _error(401, "token_expirado", "El token expiró")
        except jwt.InvalidTokenError:
            return _error(401, "token_invalido", "Token inválido (firma, issuer o audiencia)")

        g.usuario = {
            "sub": payload["sub"],
            "usuario": payload.get("preferred_username"),
            "email": payload.get("email"),
            "nombre": payload.get("name"),
            "roles": (payload.get("realm_access") or {}).get("roles", []),
            "origen": payload.get("azp"),
        }
        return f(*args, **kwargs)
    return wrapper


def tiene_rol(*roles):
    return any(r in g.usuario["roles"] for r in roles)


def es_personal():
    """True si el usuario es personal de Salud (médico, admin o recepción)."""
    return tiene_rol(*ROLES_PERSONAL)


def requiere_rol(*roles_permitidos):
    """Se usa DESPUÉS de @validar_token. Devuelve 403 si falta el rol."""
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not tiene_rol(*roles_permitidos):
                return _error(403, "permiso_denegado", "No tiene permiso para esta acción")
            return f(*args, **kwargs)
        return wrapper
    return decorador


def validar_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return jsonify(success=False, error="sin_api_key", message="No se envió la API Key en la petición"), 401
        if api_key != Config.MODULOS_API_KEY:
            return jsonify(success=False, error="api_key_invalida", message="La API Key enviada es inválida o no corresponde a un módulo autorizado"), 403
        return f(*args, **kwargs)
    return wrapper
