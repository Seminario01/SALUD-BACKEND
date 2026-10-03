#!/usr/bin/env bash
# ============================================================================
# Respaldo diario del Módulo de Salud (en el servidor)
#
#   - Base de datos de Salud (MySQL, contenedor salud-db-1)
#   - Base de datos del Login Único local (Postgres de Keycloak, rsd-postgres-local)
#
# Guarda los archivos comprimidos en ~/respaldos-salud y conserva los últimos
# DIAS_A_GUARDAR días. Pensado para correr con cron todos los días.
#
# Uso manual:   bash ~/proyecto-salud/SALUD-BACKEND/deploy/respaldo.sh
# Restaurar:    ver docs al final de deploy/README.md
# ============================================================================
set -uo pipefail

DESTINO="${DESTINO:-$HOME/respaldos-salud}"
DIAS_A_GUARDAR="${DIAS_A_GUARDAR:-7}"
DIR_COMPOSE="$(cd "$(dirname "$0")" && pwd)"
FECHA="$(date +%Y-%m-%d_%H%M)"
ERRORES=0

mkdir -p "$DESTINO"
cd "$DIR_COMPOSE" || exit 1

# --- Salud (MySQL) ----------------------------------------------------------
ARCHIVO="$DESTINO/salud_db_$FECHA.sql.gz"
if docker compose exec -T db sh -c \
     'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --default-character-set=utf8mb4 --databases salud_db' \
     2>/dev/null | gzip > "$ARCHIVO" && [ "$(gzip -cd "$ARCHIVO" | head -c 100 | wc -c)" -gt 0 ]; then
  echo "OK   Salud      -> $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"
else
  echo "FALLA Salud: no se pudo respaldar MySQL"; rm -f "$ARCHIVO"; ERRORES=1
fi

# --- Login Único local (Postgres de Keycloak) -------------------------------
if docker ps --format '{{.Names}}' | grep -q '^rsd-postgres-local$'; then
  ARCHIVO="$DESTINO/keycloak_$FECHA.sql.gz"
  if docker exec rsd-postgres-local pg_dump -U keycloak keycloak 2>/dev/null | gzip > "$ARCHIVO" \
     && [ "$(gzip -cd "$ARCHIVO" | head -c 100 | wc -c)" -gt 0 ]; then
    echo "OK   Keycloak   -> $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"
  else
    echo "FALLA Keycloak: no se pudo respaldar Postgres"; rm -f "$ARCHIVO"; ERRORES=1
  fi
fi

# --- Limpieza: solo los últimos N días --------------------------------------
find "$DESTINO" -name '*.sql.gz' -mtime +"$DIAS_A_GUARDAR" -delete

echo "Respaldos guardados: $(ls "$DESTINO"/*.sql.gz 2>/dev/null | wc -l) archivo(s) en $DESTINO"
exit $ERRORES
