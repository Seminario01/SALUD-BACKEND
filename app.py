from flask import Flask
from flasgger import Swagger
from flask_cors import CORS
from config import Config
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

    # Descarga las llaves del Login Único al arrancar: así el backend sigue
    # validando tokens aunque el servidor de identidad se apague después.
    precargar_jwks()

    return app


if __name__ == "__main__":
    app = crear_app()
    app.run(debug=True, port=5050)
