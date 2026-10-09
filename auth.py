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
ROL_ENFERMERIA = "salud:enfermeria"
ROL_RECEPCION = "salud:recepcion"
ROL_FARMACIA = "salud:farmacia"
ROL_CAJA = "salud:caja"
ROL_JEFATURA = "salud:jefatura"
ROL_ADMIN = "salud:admin"
ROL_CIUDADANO = "ciudadano"
# Auditoría Social: solo lectura de datos AGREGADOS (indicadores), nunca datos personales.
ROLES_AUDITORIA = ("auditoria:analista", "auditoria:admin")

# Personal del hospital (cualquier puesto interno).
ROLES_PERSONAL = (ROL_MEDICO, ROL_ENFERMERIA, ROL_RECEPCION, ROL_FARMACIA, ROL_CAJA, ROL_JEFATURA, ROL_ADMIN)

# ---------------------------------------------------------------------------
# MATRIZ DE PERMISOS (documento "Matriz de permisos — Módulo Salud").
# Cada permiso lista los puestos que lo tienen. Las rutas preguntan por el
# permiso, no por el rol: así la matriz se cambia en un solo lugar.
# El ciudadano no aparece aquí: accede solo a lo PROPIO (regla del dueño del dato).
# El frontend tiene la misma tabla en src/permisos.js.
# ---------------------------------------------------------------------------
MED, ENF, REC, FAR, CAJA, JEF, ADM = (ROL_MEDICO, ROL_ENFERMERIA, ROL_RECEPCION, ROL_FARMACIA,
                                      ROL_CAJA, ROL_JEFATURA, ROL_ADMIN)
PERMISOS = {
    "pacientes.ver":          (MED, ENF, REC, FAR, CAJA, JEF, ADM),
    "pacientes.registrar":    (REC, ADM),            # crear, editar todo y vincular al ciudadano
    "pacientes.antecedentes": (MED, ENF, REC, JEF),  # consulta a Seguridad
    "citas.ver":              (MED, ENF, REC, CAJA, JEF, ADM),
    "citas.gestionar":        (MED, REC),            # agendar, reprogramar, confirmar, cancelar
    "turnos.generar":         (ENF, REC),            # generar y clasificar (triaje)
    "turnos.atender":         (MED, ENF),            # llamar, atender, finalizar
    "turnos.ver_cola":        (MED, ENF, REC, JEF, ADM),
    "expediente.ver":         (MED, ENF, JEF, ADM),  # Administración: solo lectura
    "expediente.registrar":   (MED,),
    "vacunacion.ver":         (MED, ENF, JEF, ADM),
    "vacunacion.registrar":   (MED, ENF),
    "vacunacion.anular":      (JEF,),                # borrar un registro creado por error
    "recursos.ver":           (MED, ENF, REC, JEF, ADM),
    "recursos.gestionar":     (ADM,),
    "recursos.camas":         (ENF, ADM),            # actualizar disponibilidad de camas
    "pagos.verificar":        (CAJA, REC, ADM),
    "recetas.ver":            (MED, ENF, FAR, CAJA, JEF, ADM),   # Administración: solo lectura
    "recetas.crear":          (MED,),                # recetar y anular sus propias recetas pendientes
    "recetas.anular":         (MED, JEF),            # el médico, solo las suyas pendientes; Jefatura, cualquiera
    "recetas.despachar":      (FAR,),                # quien receta no despacha
    "inventario.ver":         (MED, ENF, FAR, JEF, ADM),
    "inventario.gestionar":   (FAR,),                # medicamentos nuevos, entradas y ajustes
    "hospitalizacion.ver":    (MED, ENF, REC, CAJA, JEF, ADM),   # Recepción y Caja: sin datos clínicos
    "hospitalizacion.ordenar": (MED,),               # ordenar ingreso, dar egreso, anular orden pendiente
    "hospitalizacion.camas":  (ENF,),                # asignar y trasladar cama, limpieza y mantenimiento
    "hospitalizacion.notas":  (MED, ENF),            # notas de evolución y signos vitales
    "cuentas.ver":            (REC, CAJA, ADM),      # Administración: solo lectura
    "cuentas.gestionar":      (CAJA,),               # cargos, descuentos, cierre, cobro y verificación de pago
    "panel.ver":              (MED, ENF, REC, FAR, CAJA, JEF, ADM, *ROLES_AUDITORIA),
    "presupuesto.ver":        (JEF, ADM, *ROLES_AUDITORIA),
    "presupuesto.editar":     (ADM,),
    "integraciones.ver":      (JEF, ADM),
    "integraciones.demo":     (JEF, ADM),
}


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
            # Sin esto, PyJWKClient usa urllib con su user-agent por defecto
            # ("Python-urllib/3.x"), que Cloudflare bloquea con 403 al pasar
            # por el túnel. Con un user-agent normal, la petición pasa.
            headers={"User-Agent": "salud-backend/1.0"},
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


def puede(*permisos):
    """True si el usuario tiene AL MENOS UNO de los permisos de la matriz."""
    return any(tiene_rol(*PERMISOS[p]) for p in permisos)


def permisos_de(roles):
    """Lista de permisos que dan estos roles (para GET /mis-permisos)."""
    return sorted(p for p, permitidos in PERMISOS.items() if any(r in roles for r in permitidos))


def es_personal():
    """True si el usuario es personal de Salud (cualquier puesto interno)."""
    return tiene_rol(*ROLES_PERSONAL)


def requiere_permiso(*permisos):
    """Se usa DESPUÉS de @validar_token. 403 si no tiene ninguno de los permisos."""
    for p in permisos:
        if p not in PERMISOS:
            raise ValueError(f"Permiso desconocido: {p}")

    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not puede(*permisos):
                return _error(403, "permiso_denegado", "Su puesto no tiene permiso para esta acción")
            return f(*args, **kwargs)
        return wrapper
    return decorador


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


def validar_api_key_o_token(*roles_token):
    """Para endpoints que consumen otros módulos.

    Acepta cualquiera de las dos formas:
      - X-API-Key (proceso sin usuario, servidor a servidor), o
      - el access token del usuario reenviado por el otro módulo (guía del
        Login Único, sección 7), siempre que tenga uno de roles_token.
    """
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.headers.get("X-API-Key"):
                return validar_api_key(f)(*args, **kwargs)
            if request.headers.get("Authorization", "").startswith("Bearer "):
                return validar_token(requiere_rol(*roles_token)(f))(*args, **kwargs)
            return jsonify(success=False, error="sin_credenciales",
                           message="Envíe X-API-Key o un token del Login Único"), 401
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
