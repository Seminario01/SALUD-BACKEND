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

    # Clave para LLAMAR a cada módulo (la que cada grupo nos da). Si no se
    # define, se usa MODULOS_API_KEY.
    API_KEY_EDUCACION = os.getenv("API_KEY_EDUCACION") or None
    API_KEY_SEGURIDAD = os.getenv("API_KEY_SEGURIDAD") or None
    API_KEY_TRIBUTARIO = os.getenv("API_KEY_TRIBUTARIO") or None
    # Reenviar el token del usuario a los otros módulos. Mientras cada módulo
    # use su propio Keycloak, el token no es válido en los demás: poner "false".
    REENVIAR_TOKEN_USUARIO = os.getenv("REENVIAR_TOKEN_USUARIO", "true").lower() == "true"
    # Simuladores de los otros módulos y la demostración de Integraciones: solo para las pruebas
    # (PC y GitHub). En producción (deploy/docker-compose.yml) va SIMULACIONES=false.
    SIMULACIONES = os.getenv("SIMULACIONES", "true").lower() == "true"
    # Sede donde trabaja quien no tiene otra asignada (sedes.py); es un hospital de la red del MSPAS.
    SEDE_PRINCIPAL = os.getenv("SEDE_PRINCIPAL", "Hospital Pedro de Bethancourt")
    # Documentación de la API (/apidocs): "publico" en la PC; en producción "clave" (usuario y clave
    # que se comparten con los otros grupos). Con "clave" y sin APIDOCS_CLAVE, la documentación no se muestra.
    APIDOCS = os.getenv("APIDOCS", "publico").lower()
    APIDOCS_USUARIO = os.getenv("APIDOCS_USUARIO", "modulos")
    APIDOCS_CLAVE = os.getenv("APIDOCS_CLAVE") or None

    # Alertas de Seguridad que se muestran en el panel (zona del hospital)
    DEPARTAMENTO_ALERTAS = os.getenv("DEPARTAMENTO_ALERTAS", "Sacatepéquez")
    ZONA_ALERTAS = os.getenv("ZONA_ALERTAS") or None

    # Clave que Salud ENTREGA a cada módulo para que nos consuma (una por grupo).
    # Así Salud sabe quién llamó y puede cambiar la clave de uno sin afectar a los
    # demás. MODULOS_API_KEY se sigue aceptando (simuladores y pruebas internas).
    CLAVES_ENTRADA = {
        modulo: clave for modulo, clave in {
            "Seguridad": os.getenv("CLAVE_ENTRADA_SEGURIDAD"),
            "Educación": os.getenv("CLAVE_ENTRADA_EDUCACION"),
            "Tributario": os.getenv("CLAVE_ENTRADA_TRIBUTARIO"),
            "Auditoría": os.getenv("CLAVE_ENTRADA_AUDITORIA"),
        }.items() if clave
    }
    # Tributario: tipo_obligacion que Salud envía en cada cobro. Si Tributario no
    # acepta alguno, se cambia aquí (en el .env) sin tocar código.
    TIPO_OBLIGACION_CONSULTA = os.getenv("TIPO_OBLIGACION_CONSULTA", "CONSULTA_MEDICA")
    TIPO_OBLIGACION_HOSPITALIZACION = os.getenv("TIPO_OBLIGACION_HOSPITALIZACION", "HOSPITALIZACION")
    TIPO_OBLIGACION_SERVICIOS = os.getenv("TIPO_OBLIGACION_SERVICIOS", "SERVICIOS_MEDICOS")
    # Valor de X-Modulo-Origen hacia Tributario (su documento usa "salud")
    ORIGEN_HACIA_TRIBUTARIO = os.getenv("ORIGEN_HACIA_TRIBUTARIO", "salud")
    # Tributario: vencimiento de las obligaciones de pago (días)
    DIAS_VENCIMIENTO_COBRO = int(os.getenv("DIAS_VENCIMIENTO_COBRO", "15"))

    # Monto por defecto de una consulta cuando la cita no tiene costo registrado
    COSTO_CONSULTA = float(os.getenv("COSTO_CONSULTA", "150"))