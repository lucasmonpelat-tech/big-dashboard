# Disparadores del Daily Refresh

Cómo hacer que el dashboard esté actualizado **antes de las 12:00 ART**, sin depender
del scheduler de GitHub.

---

## Por qué hace falta

Medido sobre las corridas reales de agosto:

| Período | Demora de GitHub |
|---|---|
| 19 al 26-Ago | 40–65 min (normal) |
| **27-Ago en adelante** | **260–603 min** |

**4 de las últimas 5 corridas pasaron las 15:00 UTC** (12:00 ART).

No es congestión de horario pico: el cron de Stooq, que corre a las 02:30 UTC de
madrugada, se degradó igual y el mismo día (+631, +722 min).

**El dato de Lynk sí está a tiempo** — disponible ~13:30 UTC (10:30 ART), medido
sobre 16 scrapes. Y el pipeline tarda 3 minutos. El único cuello de botella es
cuándo GitHub decide crear la corrida programada.

**El hallazgo que resuelve todo:** una corrida disparada por API se crea al
instante. En las últimas 12 corridas, la espera entre "created" y "started" fue
de **0 segundos en todas**. Solo el evento `schedule` se demora.

---

## Paso 1 — Crear el token (una sola vez)

1. Entrá a **github.com → Settings → Developer settings → Personal access tokens
   → Fine-grained tokens → Generate new token**
2. Configuralo así:

   | Campo | Valor |
   |---|---|
   | Token name | `big-dashboard-trigger` |
   | Expiration | 1 año |
   | Repository access | **Only select repositories** → `big-dashboard` |
   | Permissions | **Repository permissions → Actions → Read and write** |

   ⚠️ **Nada más.** Ni `contents`, ni `workflows`, ni otros repos.

3. Copiá el token (empieza con `github_pat_`). **Se muestra una sola vez.**

**Qué puede hacer alguien si se filtra:** disparar el refresh de ese repo. Nada
más. No da acceso al código, ni a otros repos, ni a tu cuenta.

---

## Paso 2 — Disparador local (opción A)

Anda los días que la PC está prendida. Es el más rápido: dispara y en 4 minutos
está listo.

**a) Guardar el token** — abrí PowerShell y pegá (reemplazando el token):

```
[Environment]::SetEnvironmentVariable("BIG_GH_TOKEN", "github_pat_ACA_EL_TUYO", "User")
```

Cerrá y reabrí PowerShell.

**b) Probarlo:**

```
powershell -ExecutionPolicy Bypass -File "C:\Users\lmonp\OneDrive\Desktop\Code\big-dashboard\trigger_refresh.ps1"
```

Tiene que decir `OK -- corrida creada`.

**c) Programarlo** — en PowerShell **como administrador**:

```
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\lmonp\OneDrive\Desktop\Code\big-dashboard\trigger_refresh.ps1"'
$t = New-ScheduledTaskTrigger -Daily -At 10:30
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "BIG Daily Refresh Trigger" -Action $a -Trigger $t -Settings $s -Description "Dispara el daily-refresh del BIG en GitHub"
```

`-StartWhenAvailable` hace que si la PC estaba apagada a las 10:30, dispare
apenas se prenda.

---

## Paso 3 — Disparador externo (opción B) ⭐

**Este es el importante: anda en vacaciones, con la PC apagada, siempre.**

1. Entrá a **cron-job.org** y creá una cuenta gratis.
2. **Create cronjob** con estos datos:

   | Campo | Valor |
   |---|---|
   | Title | `BIG Daily Refresh` |
   | URL | `https://api.github.com/repos/lucasmonpelat-tech/big-dashboard/actions/workflows/daily-refresh.yml/dispatches` |
   | Schedule | Lunes a Sábado, **13:30 UTC** |

3. En **Advanced**:

   - Request method: **POST**
   - Headers:
     ```
     Authorization: Bearer github_pat_ACA_EL_TUYO
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
     ```
   - Request body:
     ```json
     {"ref":"main"}
     ```

4. Guardá y usá **"Test run"** — tiene que devolver **204 No Content**. Ese es
   el código de éxito de GitHub para este endpoint (no devuelve cuerpo).

**Por qué 13:30 UTC:** es la hora a la que está disponible el NAV de Lynk,
medido. Deja 1h30 de margen contra tu deadline de las 15:00 UTC.

---

## Cómo queda

| Disparador | Cuándo | Depende de |
|---|---|---|
| **cron-job.org** | 13:30 UTC, Lun-Sáb | nada — anda siempre ⭐ |
| **Tarea local** | 10:30 ART | que la PC esté prendida |
| **Schedule de GitHub** | 12:30 UTC | GitHub (hoy poco confiable) |
| **Watchdog** | 16:07 UTC | GitHub, es la última red |

Cuatro intentos independientes. **Correr de más no hace daño**: el workflow
tiene guard de idempotencia — si ya corrió hoy, el segundo gatillo se saltea solo
sin entrar a NetX360 de nuevo.

Para forzar una corrida igual: `trigger_refresh.ps1 -Force`, o desde la web con
el input `force` en true.

---

## Si algo falla

| Síntoma | Causa |
|---|---|
| `401` | token vencido o mal copiado → regeneralo |
| `403` | al token le falta **Actions: Read and write** |
| `404` | el nombre del repo o del workflow está mal escrito |
| Devuelve 204 pero no aparece corrida | ya corrió hoy y el guard la salteó — es correcto |
