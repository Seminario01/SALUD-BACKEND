from flask import Flask, jsonify, request
from flasgger import Swagger
from sqlalchemy.exc import DataError, IntegrityError
from werkzeug.exceptions import HTTPException
from flask_cors import CORS
from config import Config
import migraciones
from extensions import db
from routes.init import registrar_rutas
from auth import precargar_jwks
from validacion import DatoInvalido
from bitacora_accesos import registrar_acceso
import auditoria_registro

SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "API Módulo de Salud",
        "description": "Endpoints del módulo de Salud y de integración con otros módulos del sistema.",
        "version": "1.0.0",
    },
    "securityDefinitions": {
        "BearerAuth": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "Access token del Login Único (Keycloak). Formato: Bearer <token>",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "name": "X-API-Key",
            "in": "header",
            "description": "API key para comunicación server-to-server entre módulos.",
        },
    },
}


def crear_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=Config.CORS_ORIGINS, supports_credentials=True)

    db.init_app(app)
    registrar_rutas(app)
    Swagger(app, template=SWAGGER_TEMPLATE)

    with app.app_context():
        db.create_all()
        migraciones.aplicar(db)   # columnas nuevas en tablas que ya existían

    # Descarga las llaves del Login Único al arrancar: así el backend sigue
    # validando tokens aunque el servidor de identidad se apague después.
    precargar_jwks()

    # Bitácora de accesos: quién vio o modificó datos de pacientes (bitacora_accesos.py)
    app.after_request(registrar_acceso)
    # Cada consulta de Auditoría Social, también las rechazadas, con su motivo (auditoria_registro.py)
    app.before_request(auditoria_registro.inicio)
    app.after_request(auditoria_registro.registrar_consulta)

    # Errores de la API siempre en JSON (los otros módulos esperan {"success": false, ...})
    @app.errorhandler(404)
    def no_encontrado(_e):
        return jsonify(success=False, error="no_encontrado", message="La ruta solicitada no existe"), 404

    @app.errorhandler(405)
    def metodo_no_permitido(_e):
        return jsonify(success=False, error="metodo_no_permitido", message="Método HTTP no permitido en esta ruta"), 405

    # Un cuerpo que no es un objeto JSON ({...}) se rechaza antes de llegar a la ruta:
    # null, [], texto suelto o JSON mal escrito responden 400 y no 500.
    @app.before_request
    def cuerpo_debe_ser_objeto():
        if request.method in ("POST", "PUT", "PATCH") and request.get_data(cache=True):
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(success=False, error="datos_invalidos",
                               message="El cuerpo debe ser un objeto JSON con Content-Type: application/json"), 400

    @app.errorhandler(DatoInvalido)
    def dato_invalido(e):
        db.session.rollback()
        codigo = "ya_existe" if e.status == 409 else "datos_invalidos"
        return jsonify(success=False, error=codigo, message=e.mensaje), e.status

    # Red de seguridad: un dato que no cabe en la columna o un duplicado que se escapó
    # de la validación de la ruta no debe convertirse en un 500.
    @app.errorhandler(DataError)
    def dato_fuera_de_rango(_e):
        db.session.rollback()
        return jsonify(success=False, error="datos_invalidos",
                       message="Algún dato es demasiado largo o tiene un valor fuera de rango"), 400

    @app.errorhandler(IntegrityError)
    def dato_duplicado(_e):
        db.session.rollback()
        return jsonify(success=False, error="conflicto",
                       message="El registro ya existe o depende de otro que no existe"), 409

    # Cualquier otro error HTTP (400, 413, 415...) también en JSON, nunca la página HTML de Flask.
    @app.errorhandler(HTTPException)
    def error_http(e):
        return jsonify(success=False, error=(e.name or "error").lower().replace(" ", "_"),
                       message=e.description), e.code

    @app.errorhandler(500)
    def error_interno(_e):
        db.session.rollback()
        return jsonify(success=False, error="error_interno",
                       message="Error interno del Módulo de Salud. Intente de nuevo más tarde."), 500

    return app


if __name__ == "__main__":
    app = crear_app()
    app.run(debug=True, port=5050)
