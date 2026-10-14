# ============================================================================
# Copia los respaldos del servidor a esta PC (se corre en la PC, en PowerShell)
#
# respaldo.sh deja los respaldos en ~/respaldos-salud del servidor. Si ese disco
# falla, se pierden junto con el sistema; por eso esta PC trae una copia.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File C:\Denis\SALUD-BACKEND\deploy\copiar_respaldos.ps1 -Servidor denis@IP_DEL_SERVIDOR
#
# Para que corra solo (Programador de tareas) se necesita una llave SSH, porque
# no hay nadie para escribir la contraseña. Pasos en deploy/README.md, sección 7.
# ============================================================================
param(
    [Parameter(Mandatory = $true)][string]$Servidor,      # usuario@ip, el mismo con que entra por SSH
    [string]$Destino = "$env:USERPROFILE\Respaldos-Salud",
    [int]$DiasAGuardar = 30
)

New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$log = Join-Path $Destino "copias.log"
$fecha = Get-Date -Format "yyyy-MM-dd HH:mm"

# -p conserva la fecha de cada archivo (la usa la limpieza). BatchMode: si falta la llave SSH falla de inmediato en vez de quedarse esperando la contraseña
scp -p -o BatchMode=yes -o ConnectTimeout=20 "${Servidor}:respaldos-salud/*.sql.gz" "$Destino\"
if ($LASTEXITCODE -ne 0) {
    "$fecha  FALLA: no se pudo copiar desde $Servidor (¿servidor apagado o sin llave SSH?)" | Add-Content $log
    Write-Host "FALLA: no se pudieron copiar los respaldos. Detalle en $log"
    exit 1
}

# Solo los últimos N días, igual que en el servidor (pero más tiempo)
Get-ChildItem $Destino -Filter *.sql.gz |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$DiasAGuardar) } |
    Remove-Item -Confirm:$false

$total = (Get-ChildItem $Destino -Filter *.sql.gz).Count
"$fecha  OK: $total respaldo(s) en $Destino" | Add-Content $log
Write-Host "OK: $total respaldo(s) en $Destino"
