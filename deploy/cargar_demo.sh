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
#   ssh denis@IP 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/cargar_demo.sh --hoy'      fechas al día y turnos de hoy
# --hoy (para el día de la presentación): mueve las fechas de los datos demo como si se hubieran
# cargado hoy (demo_refrescar_fechas.sql: mapa, brotes, citas de hoy, recetas pendientes) y carga
# los turnos de la sala de espera. Se puede correr todos los días; no duplica nada.
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
if [ "${1:-}" = "--hoy" ]; then
  cargar demo_refrescar_fechas.sql
  cargar demo_turnos_hoy.sql
elif [ "${1:-}" = "--turnos" ]; then
  cargar demo_turnos_hoy.sql
fi
echo "=== Listo"
