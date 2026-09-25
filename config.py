import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://usuario:password@localhost/salud_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Login Único (Keycloak). El issuer cambia cada día mientras el servicio corra
    # sobre un túnel temporal: se configura SOLO en el .env, nunca en el código.
    # Ejemplo: https://<url-del-dia>.trycloudflare.com/realms/rsd
    AUTH_ISSUER = os.getenv("AUTH_ISSUER", "http://localhost:8081/realms/rsd").rstrip("/")
    AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE", "rsd-api")
    AUTH_JWKS_URL = f"{AUTH_ISSUER}/protocol/openid-connect/certs"

    # API Key para comunicación server-to-server con otros módulos
    MODULOS_API_KEY = os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")

    # Orígenes permitidos para CORS (frontend en desarrollo con Vite)
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:4200,http://127.0.0.1:4200,http://localhost:5173"
    ).split(",")

    # URLs base de los módulos externos del sistema
    URL_EDUCACION = os.getenv("URL_EDUCACION", "http://localhost:5001")
    URL_SEGURIDAD = os.getenv("URL_SEGURIDAD", "http://localhost:5002")
    URL_TRIBUTARIO = os.getenv("URL_TRIBUTARIO", "http://localhost:5003")