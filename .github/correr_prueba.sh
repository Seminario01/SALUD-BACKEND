#!/usr/bin/env bash
# Corre una prueba en GitHub Actions. Si falla, publica como avisos (Annotations) las líneas
# con FALLA y el final del error, para verlos en la página de la corrida sin iniciar sesión.
set -o pipefail
PRUEBA="$1"
SALIDA="$(mktemp)"
python "$PRUEBA" 2>&1 | tee "$SALIDA"
CODIGO=${PIPESTATUS[0]}
if [ "$CODIGO" != 0 ]; then
  grep -E "FALLA|No se pudo|Error|error" "$SALIDA" | head -n 15 | while IFS= read -r linea; do
    echo "::error title=${PRUEBA##*/}::${linea//%/%25}"
  done
  echo "::error title=${PRUEBA##*/} (final de la salida)::$(tail -n 6 "$SALIDA" | tr '\n' ' ' | sed 's/%/%25/g' | cut -c1-900)"
fi
exit "$CODIGO"
