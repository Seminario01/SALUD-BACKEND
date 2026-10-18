#!/usr/bin/env bash
# ============================================================================
# Prueba que el último respaldo de Salud SÍ se puede restaurar (en el servidor)
#
# Levanta un MySQL TEMPORAL y aislado (sin red ni puertos, contenedor
# salud-prueba-restauracion), restaura ahí el respaldo, cuenta los registros de las
# tablas principales, los compara con producción y borra el contenedor al terminar.
# Producción no se toca: solo se le hacen consultas COUNT(*) de lectura.
#
# Uso:        bash ~/proyecto-salud/SALUD-BACKEND/deploy/probar_respaldo.sh [archivo.sql.gz]
#             bash ~/proyecto-salud/SALUD-BACKEND/deploy/probar_respaldo.sh --programar   (cada domingo, 4:00)
#             (sin archivo, usa el respaldo más reciente de ~/respaldos-salud)
# Registro:   ~/respaldos-salud/prueba-restauracion.log (una línea por prueba; estado.sh la muestra)
# ============================================================================
set -uo pipefail

CARPETA="${CARPETA:-$HOME/respaldos-salud}"
REGISTRO="$CARPETA/prueba-restauracion.log"
CONTENEDOR="salud-prueba-restauracion"
IMAGEN="mysql:8.0"                         # la misma de producción (ya está descargada)
DIR_COMPOSE="${DIR_COMPOSE:-$(cd "$(dirname "$0")" && pwd)}"
TABLAS="pacientes citas_medicas expedientes_clinicos recetas medicamentos hospitalizaciones cuentas_paciente vacunacion bitacora_accesos"

# --programar: deja la prueba en cron todos los domingos a las 4:00 (después del respaldo de las 3:15)
if [ "${1:-}" = "--programar" ]; then
  RUTA="$(cd "$(dirname "$0")" && pwd)/probar_respaldo.sh"
  if crontab -l 2>/dev/null | grep -q probar_respaldo.sh; then
    echo "Ya estaba programada:"; crontab -l | grep probar_respaldo.sh
  else
    mkdir -p "$CARPETA"
    (crontab -l 2>/dev/null; echo "0 4 * * 0 bash $RUTA >> $CARPETA/prueba-restauracion-detalle.log 2>&1") | crontab -
    echo "Programada todos los domingos a las 4:00:"; crontab -l | grep probar_respaldo.sh
  fi
  exit 0
fi

ARCHIVO="${1:-$(ls -t "$CARPETA"/salud_db_*.sql.gz 2>/dev/null | head -n 1)}"
mkdir -p "$CARPETA"
ahora() { date '+%Y-%m-%d %H:%M'; }
fallar() {
  echo "FALLA: $1"
  echo "$(ahora)  FALLA  ${ARCHIVO##*/}: $1" >> "$REGISTRO"
  exit 1
}

[ -n "$ARCHIVO" ] && [ -f "$ARCHIVO" ] || fallar "no hay respaldos en $CARPETA"
gzip -t "$ARCHIVO" 2>/dev/null || fallar "el archivo está dañado (gzip no lo puede leer)"
echo "Respaldo a probar: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1), $(date -r "$ARCHIVO" '+%Y-%m-%d %H:%M'))"

# Clave al azar solo para este MySQL temporal: no se guarda en ningún lado y muere con el contenedor
CLAVE="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
ERRORES_MYSQL="$(mktemp)"
limpiar() { docker rm -f "$CONTENEDOR" >/dev/null 2>&1; rm -f "$ERRORES_MYSQL"; }
trap limpiar EXIT
docker rm -f "$CONTENEDOR" >/dev/null 2>&1

echo "Levantando MySQL temporal y aislado..."
docker run -d --name "$CONTENEDOR" --network none --memory 700m \
  -e MYSQL_ROOT_PASSWORD="$CLAVE" "$IMAGEN" --skip-log-bin >/dev/null </dev/null \
  || fallar "no se pudo levantar el MySQL temporal"

# Consultas al MySQL temporal: sin leer la entrada (</dev/null), así no se "comen" nada
temporal() { docker exec -e MYSQL_PWD="$CLAVE" "$CONTENEDOR" mysql -uroot -N --default-character-set=utf8mb4 -e "$1" </dev/null; }
# Restauración: el respaldo entra por la entrada estándar
restaurar() { docker exec -i -e MYSQL_PWD="$CLAVE" "$CONTENEDOR" mysql -uroot --default-character-set=utf8mb4; }
# Consultas de solo lectura a producción (la clave la pone el propio contenedor)
produccion() {
  (cd "$DIR_COMPOSE" && docker compose exec -T -e CONSULTA="$1" db \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "$CONSULTA"' </dev/null 2>/dev/null) | tr -d '\r'
}

# La imagen de MySQL arranca, se configura y se reinicia: esperar a que acepte consultas de verdad
for _ in $(seq 1 90); do
  if docker logs "$CONTENEDOR" 2>&1 | grep -q "ready for connections.*port: 3306" \
     && temporal "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
temporal "SELECT 1" >/dev/null 2>&1 || fallar "el MySQL temporal no arrancó"

echo "Restaurando..."
INICIO=$SECONDS
gzip -cd "$ARCHIVO" | restaurar 2>"$ERRORES_MYSQL" || fallar "MySQL rechazó el respaldo: $(head -c 200 "$ERRORES_MYSQL")"
SEGUNDOS=$((SECONDS - INICIO))

CONTAR_TABLAS="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='salud_db'"
TABLAS_RESPALDO="$(temporal "$CONTAR_TABLAS")"
TABLAS_PRODUCCION="$(produccion "$CONTAR_TABLAS")"

printf '\n%-24s %10s %12s\n' "Tabla" "Respaldo" "Producción"
PROBLEMAS=0
RESUMEN=""
for t in $TABLAS; do
  r="$(temporal "SELECT COUNT(*) FROM salud_db.$t" 2>/dev/null)"
  p="$(produccion "SELECT COUNT(*) FROM salud_db.$t")"
  marca=""
  if [ -z "$r" ]; then
    marca="  <- falta en el respaldo"; PROBLEMAS=$((PROBLEMAS + 1))
  elif [ -n "$p" ] && [ "$r" -gt "$p" ]; then
    marca="  <- el respaldo tiene MÁS que producción"; PROBLEMAS=$((PROBLEMAS + 1))
  fi
  printf '%-24s %10s %12s%s\n' "$t" "${r:-?}" "${p:-?}" "$marca"
  RESUMEN="$RESUMEN $t=${r:-?}"
done
PACIENTES="$(temporal "SELECT COUNT(*) FROM salud_db.pacientes" 2>/dev/null)"
[ "${PACIENTES:-0}" -gt 0 ] || { echo "El respaldo no tiene pacientes"; PROBLEMAS=$((PROBLEMAS + 1)); }
echo
echo "Tablas: ${TABLAS_RESPALDO:-?} en el respaldo, ${TABLAS_PRODUCCION:-?} en producción."
echo "(Producción puede tener más registros: son los creados después de la hora del respaldo.)"

[ "$PROBLEMAS" = 0 ] || fallar "$PROBLEMAS problema(s) al comparar con producción"
echo "$(ahora)  OK     ${ARCHIVO##*/} se restauró en ${SEGUNDOS}s;$RESUMEN" >> "$REGISTRO"
echo "=== El respaldo SÍ se puede restaurar (en ${SEGUNDOS} s). Contenedor temporal borrado."
