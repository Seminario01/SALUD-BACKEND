#!/usr/bin/env bash
# ============================================================================
# Carga (o completa) los datos de demostración en la base que ya está corriendo
#
# datos_demo.sql y demo_turnos_hoy.sql de SALUD-DATABASE se pueden correr varias veces:
# solo agregan lo que falta (por ejemplo laboratorio, constancias o lista de espera
# cuando se agregaron esas funciones). Primero actualiza SALUD-DATABASE con git pull.
#
# Uso (desde la PC):
#   ssh denis@IP 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/cargar_demo.sh'            datos demo
#   ssh denis@IP 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/cargar_demo.sh --turnos'   y turnos de hoy
# La clave de MySQL la pone el propio contenedor: no se escribe en ningún comando.
# ============================================================================
set -euo pipefail
DEPLOY="$(cd "$(dirname "$0")" && pwd)"
BASE="$DEPLOY/../../SALUD-DATABASE"

[ -f "$BASE/datos_demo.sql" ] || { echo "No encuentro $BASE/datos_demo.sql"; exit 1; }
git -C "$BASE" pull -q origin denilson-dev && echo "SALUD-DATABASE: $(git -C "$BASE" log --oneline -1 | cut -c1-7)"

cargar() {
  echo "Cargando $1..."
  (cd "$DEPLOY" && docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --default-character-set=utf8mb4 -N') < "$BASE/$1"
}

cargar datos_demo.sql
# Pacientes y atenciones de todo el país (mapa de vigilancia, recetas, crecimiento). Una sola vez.
[ -f "$BASE/demo_poblacion.sql" ] && cargar demo_poblacion.sql
[ "${1:-}" = "--turnos" ] && cargar demo_turnos_hoy.sql
echo "=== Listo"
