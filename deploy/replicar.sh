#!/usr/bin/env bash
# ============================================================================
# Replica producción en el servidor de RESPALDO (se corre en el respaldo)
#
#   1. Código: git pull de los tres repos (rama denilson-dev).
#   2. Levanta todo con docker compose (el túnel de Cloudflare NO: el respaldo
#      no se publica; si los dos tuvieran el túnel, las visitas se repartirían).
#   3. Datos: le pide a producción un respaldo nuevo, lo trae y lo restaura aquí.
#      Las copias quedan en ~/respaldos-de-produccion (últimos 30 días): así hay
#      un respaldo fuera de producción.
#
# Uso (desde la PC):
#   ssh denis@IP_DEL_RESPALDO 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/replicar.sh denis@IP_DE_PRODUCCION'
#
# Necesita una llave SSH de este servidor hacia producción (deploy/README.md, sección 10).
# ============================================================================
set -euo pipefail

PRODUCCION="${1:?Indique el servidor de producción, por ejemplo denis@100.70.58.32}"
RAIZ="$HOME/proyecto-salud"
COPIAS="$HOME/respaldos-de-produccion"
DIAS_A_GUARDAR=30

echo "=== 1. Código"
for repo in SALUD-BACKEND SALUD-FRONTEND SALUD-DATABASE; do
  git -C "$RAIZ/$repo" pull -q origin denilson-dev
  echo "OK   $repo -> $(git -C "$RAIZ/$repo" log --oneline -1)"
done

echo "=== 2. Contenedores"
cd "$RAIZ/SALUD-BACKEND/deploy"
docker compose up -d --build --quiet-pull 2>&1 | tail -n 5
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q db)")" = "healthy" ] && break
  sleep 2
done
docker compose ps --format 'table {{.Name}}\t{{.Status}}'

echo "=== 3. Datos de producción"
mkdir -p "$COPIAS"
ULTIMO="$(ssh -o BatchMode=yes "$PRODUCCION" \
  'bash ~/proyecto-salud/SALUD-BACKEND/deploy/respaldo.sh >/dev/null; ls -t ~/respaldos-salud/salud_db_*.sql.gz | head -n 1')"
scp -q -p -o BatchMode=yes "$PRODUCCION:$ULTIMO" "$COPIAS/"
ARCHIVO="$COPIAS/$(basename "$ULTIMO")"
gunzip -c "$ARCHIVO" | docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' 2>/dev/null
echo "OK   restaurado $(basename "$ARCHIVO")"
find "$COPIAS" -name '*.sql.gz' -mtime +"$DIAS_A_GUARDAR" -delete

echo "=== Comparación (deben coincidir)"
CONTEO='select (select count(*) from pacientes), (select count(*) from citas_medicas)'
echo "Producción   pacientes y citas: $(ssh -o BatchMode=yes "$PRODUCCION" \
  "cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose exec -T db sh -c 'mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N salud_db -e \"$CONTEO\"' 2>/dev/null")"
echo "Respaldo     pacientes y citas: $(docker compose exec -T db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N salud_db -e \"$CONTEO\"" 2>/dev/null)"
echo "Réplica terminada: $(date '+%Y-%m-%d %H:%M')"
