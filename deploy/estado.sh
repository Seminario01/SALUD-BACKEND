#!/usr/bin/env bash
# ============================================================================
# Revisión rápida del Módulo de Salud en ESTE servidor (solo lee, no cambia nada)
#
# Sabe solo si es producción (tiene el túnel encendido) o el respaldo, y revisa lo
# que corresponde a cada uno. Cada línea dice OK o REVISAR.
#
# Uso (desde la PC):
#   ssh denis@IP 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/estado.sh'
# ============================================================================
set -uo pipefail
cd "$HOME/proyecto-salud/SALUD-BACKEND/deploy" || { echo "REVISAR  no existe ~/proyecto-salud"; exit 1; }

PROBLEMAS=0
ok()      { printf 'OK       %s\n' "$1"; }
revisar() { printf 'REVISAR  %s\n' "$1"; PROBLEMAS=$((PROBLEMAS + 1)); }
# Horas desde que se modificó el archivo más nuevo que coincide con el patrón (vacío si no hay)
horas_desde() { local f; f="$(ls -t $1 2>/dev/null | head -n 1)"; [ -n "$f" ] && echo $(( ($(date +%s) - $(stat -c %Y "$f")) / 3600 )); }

if [ -n "$(docker ps -q --filter name=^salud-tunel-1$)" ]; then ROL="PRODUCCIÓN"; else ROL="RESPALDO"; fi
echo "=== $(hostname) ($ROL)  $(date '+%Y-%m-%d %H:%M')"

# --- Código
echo "         código: backend $(git -C .. log --oneline -1 | cut -c1-7), frontend $(git -C ../../SALUD-FRONTEND log --oneline -1 | cut -c1-7)"

# --- Contenedores
ESPERADOS="db backend frontend simuladores"
[ "$ROL" = "PRODUCCIÓN" ] && ESPERADOS="$ESPERADOS tunel"
for s in $ESPERADOS; do
  estado="$(docker compose ps --format '{{.State}}' "$s" 2>/dev/null)"
  [ "$estado" = "running" ] && ok "contenedor $s" || revisar "contenedor $s: ${estado:-no existe}"
done
salud_db="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q db)" 2>/dev/null)"
[ "$salud_db" = "healthy" ] && ok "base de datos lista" || revisar "base de datos: ${salud_db:-sin datos}"

# --- Respaldos y réplica
if [ "$ROL" = "PRODUCCIÓN" ]; then
  h="$(horas_desde "$HOME/respaldos-salud/salud_db_*.sql.gz")"
  { [ -n "$h" ] && [ "$h" -lt 26 ]; } && ok "último respaldo hace ${h} h" || revisar "último respaldo: ${h:-ninguno} h (debe ser menos de 26)"
  crontab -l 2>/dev/null | grep -q respaldo.sh && ok "respaldo diario programado (3:15)" || revisar "falta programar respaldo.sh en crontab"
else
  [ -z "$(docker ps -q --filter name=^salud-tunel-1$)" ] && ok "túnel apagado (correcto en el respaldo)"
  h="$(horas_desde "$HOME/respaldos-de-produccion/salud_db_*.sql.gz")"
  { [ -n "$h" ] && [ "$h" -lt 26 ]; } && ok "última réplica hace ${h} h" || revisar "última réplica: ${h:-ninguna} h (debe ser menos de 26)"
  crontab -l 2>/dev/null | grep -q replicar.sh && ok "réplica diaria programada (3:45)" || revisar "falta programar replicar.sh en crontab"
  crontab -l 2>/dev/null | grep -q vigilar.sh && ok "vigilancia programada (cada 5 min)" || revisar "falta programar vigilar.sh en crontab"
  case "$(cat "$HOME/respaldos-de-produccion/.vigilancia-estado" 2>/dev/null)" in
    EN_LINEA) ok "vigilancia: la página está en línea" ;;
    CAIDA)    revisar "vigilancia: la página está CAÍDA (ver vigilancia.log)" ;;
    *)        ok "vigilancia: todavía no ha corrido (corre cada 5 minutos)" ;;
  esac
  ultima="$(grep -E 'CAIDA|RECUPERADA' "$HOME/respaldos-de-produccion/vigilancia.log" 2>/dev/null | tail -n 1)"
  [ -n "$ultima" ] && echo "         último cambio registrado: $ultima"
fi

# --- Disco y página
uso="$(df --output=pcent "$HOME" | tail -n 1 | tr -dc 0-9)"
[ "$uso" -lt 85 ] && ok "disco al ${uso}%" || revisar "disco al ${uso}% (liberar espacio)"
pagina="$(curl -s -o /dev/null -m 20 -w '%{http_code}' https://saludumg.online/)"
[ "$pagina" = "200" ] && ok "saludumg.online responde" || revisar "saludumg.online responde $pagina"

echo "=== $([ "$PROBLEMAS" = 0 ] && echo 'Todo bien' || echo "$PROBLEMAS punto(s) para revisar")"
