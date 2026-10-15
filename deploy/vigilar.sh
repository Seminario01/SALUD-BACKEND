#!/usr/bin/env bash
# ============================================================================
# Vigila https://saludumg.online desde el servidor de RESPALDO (cron cada 5 minutos)
#
# Revisa la página y la API pasando por Cloudflare, igual que un usuario. Solo anota
# cuando algo CAMBIA (se cae o se recupera), así el registro queda corto y fácil de leer.
# Cuando se cae, anota también si producción responde por SSH y cómo están sus
# contenedores, para saber de un vistazo si falló el túnel, la app o el servidor.
#
# Registro:  ~/respaldos-de-produccion/vigilancia.log
# Uso:       bash vigilar.sh denis@IP_DE_PRODUCCION
# ============================================================================
set -uo pipefail

PRODUCCION="${1:?Indique el servidor de producción, por ejemplo denis@100.70.58.32}"
SITIO="${SITIO:-https://saludumg.online}"
CARPETA="${CARPETA:-$HOME/respaldos-de-produccion}"
REGISTRO="$CARPETA/vigilancia.log"
ESTADO="$CARPETA/.vigilancia-estado"
mkdir -p "$CARPETA"

ahora() { date '+%Y-%m-%d %H:%M'; }
codigo() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$1"; }

# Dos intentos separados por 20 s: un parpadeo de la red no cuenta como caída
for intento in 1 2; do
  PAGINA="$(codigo "$SITIO/")"
  API="$(codigo "$SITIO/api/v1/salud/indicadores")"   # sin credenciales: 401 = la API responde
  if [ "$PAGINA" = "200" ] && { [ "$API" = "401" ] || [ "$API" = "200" ]; }; then
    NUEVO="EN_LINEA"; break
  fi
  NUEVO="CAIDA"
  [ "$intento" = 1 ] && sleep 20
done

ANTERIOR="$(cat "$ESTADO" 2>/dev/null || echo EN_LINEA)"
echo "$NUEVO" > "$ESTADO"
[ "$NUEVO" = "$ANTERIOR" ] && exit 0

if [ "$NUEVO" = "CAIDA" ]; then
  echo "$(ahora)  CAIDA       página $PAGINA, API $API" >> "$REGISTRO"
  if DETALLE="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$PRODUCCION" \
      'cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose ps --format "{{.Service}}={{.State}}" | tr "\n" " "' 2>/dev/null)"; then
    echo "                  producción responde por SSH; contenedores: $DETALLE" >> "$REGISTRO"
  else
    echo "                  producción NO responde por SSH (servidor apagado o sin red)" >> "$REGISTRO"
  fi
else
  echo "$(ahora)  RECUPERADA  página $PAGINA, API $API" >> "$REGISTRO"
fi
