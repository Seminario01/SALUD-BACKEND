from flask import Flask
from flasgger import Swagger
from config import Config
from extensions import db
from routes.init import registrar_rutas

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
            "description": "Token JWT de Cognito. Formato: Bearer <token>",
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

    db.init_app(app)
    registrar_rutas(app)
    Swagger(app, template=SWAGGER_TEMPLATE)

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = crear_app()
    app.run(debug=True, port=5000)
