FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Zonas horarias: sin tzdata, TZ=America/Guatemala no tiene efecto y la hora
# "local" sería UTC (afecta la numeración diaria de turnos).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios
RUN useradd --create-home salud && chown -R salud /app
USER salud

EXPOSE 5050

# --preload: crea la app UNA vez antes de crear los workers. Evita la carrera de
#   db.create_all() con varios workers y descarga las llaves del Login Único
#   (JWKS) una sola vez; los workers heredan la caché.
CMD ["gunicorn", "--preload", "--workers", "2", "--bind", "0.0.0.0:5050", \
     "--access-logfile", "-", "--timeout", "60", "app:crear_app()"]
