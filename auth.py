import jwt
import requests
from functools import wraps
from flask import request, jsonify, g
from jwt import PyJWKClient
from config import Config
from models import UsuarioRol

_jwk_client = None

def get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(Config.COGNITO_JWKS_URL)
    return _jwk_client


def validar_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(success=False, error="sin_token", message="Falta el token"), 401

        token = auth_header.split(" ")[1]
        try:
            signing_key = get_jwk_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False})
        except Exception:
            return jsonify(success=False, error="token_invalido", message="Token inválido o expirado"), 401

        sub = payload.get("sub")
        email = payload.get("email")

        usuario = UsuarioRol.query.filter_by(cognito_sub=sub).first()
        if not usuario or not usuario.activo:
            return jsonify(success=False, error="usuario_no_autorizado", message="Usuario no registrado en Salud"), 403

        g.usuario = usuario
        return f(*args, **kwargs)
    return wrapper


def requiere_rol(*roles_permitidos):
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.usuario.rol not in roles_permitidos:
                return jsonify(success=False, error="permiso_denegado", message="No tiene permiso para esta acción"), 403
            return f(*args, **kwargs)
        return wrapper
    return decorador


def validar_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key != Config.MODULOS_API_KEY:
            return jsonify(success=False, error="api_key_invalida", message="API key inválida"), 403
        return f(*args, **kwargs)
    return wrapper