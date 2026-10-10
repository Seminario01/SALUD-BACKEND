from flask import Flask, jsonify
from flasgger import Swagger
from flask_cors import CORS
from config import Config
import migraciones
from extensions import db
from routes.init import registrar_rutas
from auth import precargar_jwks

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

    # Errores de la API siempre en JSON (los otros módulos esperan {"success": false, ...})
    @app.errorhandler(404)
    def no_encontrado(_e):
        return jsonify(success=False, error="no_encontrado", message="La ruta solicitada no existe"), 404

    @app.errorhandler(405)
    def metodo_no_permitido(_e):
        return jsonify(success=False, error="metodo_no_permitido", message="Método HTTP no permitido en esta ruta"), 405

    @app.errorhandler(500)
    def error_interno(_e):
        db.session.rollback()
        return jsonify(success=False, error="error_interno",
                       message="Error interno del Módulo de Salud. Intente de nuevo más tarde."), 500

    return app


if __name__ == "__main__":
    app = crear_app()
    app.run(debug=True, port=5050)
