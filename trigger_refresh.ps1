# =============================================================================
#  trigger_refresh.ps1 — dispara el Daily Refresh del BIG en GitHub
# =============================================================================
#
#  POR QUE EXISTE (2026-08-31)
#  ---------------------------
#  GitHub retrasa las corridas PROGRAMADAS. Medido sobre 11 corridas:
#      19 al 26-ago   40 a 65 min de demora  (normal)
#      27-ago en adelante   260 a 603 min    (4 de 5 pasaron el deadline)
#  Y no es congestion de horario: el cron de Stooq, que corre 02:30 UTC de
#  madrugada, se degrado igual y el mismo dia (+631, +722 min).
#
#  En cambio una corrida disparada por API se crea AL INSTANTE: se midio la
#  espera entre "created" y "started" en las ultimas 12 corridas y da 0 segundos
#  en todas. El cuello de botella es exclusivamente CUANDO GitHub decide crear
#  la corrida programada.
#
#  Este script llama a la API y la crea al toque.
#
#  EL TOKEN
#  --------
#  Necesita un Personal Access Token de GitHub. Crear uno FINE-GRAINED, acotado:
#
#     github.com -> Settings -> Developer settings
#     -> Personal access tokens -> Fine-grained tokens -> Generate new token
#
#     Repository access : Only select repositories -> big-dashboard
#     Permissions       : Repository permissions -> Actions -> Read and write
#                         (NADA MAS -- ni contents, ni workflows)
#     Expiration        : 1 anio
#
#  Con ese permiso, lo unico que se puede hacer con el token es disparar
#  workflows en ESE repo. No da acceso al codigo, ni a otros repos, ni a la
#  cuenta.
#
#  Guardarlo como variable de entorno del usuario (NO en este archivo):
#     [Environment]::SetEnvironmentVariable("BIG_GH_TOKEN", "ghp_xxx", "User")
#  Cerrar y reabrir la terminal para que tome.
#
#  USO
#  ---
#     powershell -ExecutionPolicy Bypass -File trigger_refresh.ps1
#     powershell -ExecutionPolicy Bypass -File trigger_refresh.ps1 -Force
#
#  El workflow tiene guard de idempotencia: si ya corrio hoy, se saltea solo.
#  -Force lo corre igual.
# =============================================================================

param([switch]$Force)

$ErrorActionPreference = "Stop"

$repo     = "lucasmonpelat-tech/big-dashboard"
$workflow = "daily-refresh.yml"
$token    = $env:BIG_GH_TOKEN

if (-not $token) {
    Write-Host "ERROR: falta la variable de entorno BIG_GH_TOKEN." -ForegroundColor Red
    Write-Host "Ver las instrucciones en la cabecera de este archivo." -ForegroundColor Yellow
    exit 1
}

$uri  = "https://api.github.com/repos/$repo/actions/workflows/$workflow/dispatches"
$body = @{ ref = "main"; inputs = @{ force = $Force.IsPresent.ToString().ToLower() } } | ConvertTo-Json

$headers = @{
    Authorization          = "Bearer $token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "big-dashboard-trigger"
}

$ahora = (Get-Date).ToString("yyyy-MM-dd HH:mm")
Write-Host "[$ahora] Disparando $workflow (force=$($Force.IsPresent))..."

try {
    Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ContentType "application/json" | Out-Null
    Write-Host "OK -- corrida creada. Termina en ~4 minutos." -ForegroundColor Green
    Write-Host "https://github.com/$repo/actions/workflows/$workflow"
    exit 0
}
catch {
    Write-Host "FALLO al disparar: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "401 = token invalido o vencido. Regenerarlo." -ForegroundColor Yellow
    }
    elseif ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "403 = al token le falta el permiso Actions: Read and write." -ForegroundColor Yellow
    }
    exit 1
}
