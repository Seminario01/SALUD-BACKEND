import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://usuario:password@localhost/salud_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    COGNITO_REGION = os.getenv("COGNITO_REGION", "us-east-1")
    COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
    COGNITO_JWKS_URL = (
        f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
        f"{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )

    # API Key para comunicación server-to-server con otros módulos
    MODULOS_API_KEY = os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")

    # Orígenes permitidos para CORS (frontend en desarrollo con Vite)
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")

    # URLs base de los módulos externos del sistema
    URL_EDUCACION = os.getenv("URL_EDUCACION", "http://localhost:5001")
    URL_SEGURIDAD = os.getenv("URL_SEGURIDAD", "http://localhost:5002")
    URL_TRIBUTARIO = os.getenv("URL_TRIBUTARIO", "http://localhost:5003")