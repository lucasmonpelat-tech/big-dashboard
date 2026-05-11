# 🚀 Mejoras Propuestas del HTML para Mejor Toma de Decisiones

> Documento para revisar con Lucas. Propuestas priorizadas por impacto/esfuerzo.

---

## 🎯 La pregunta clave que el HTML debe responder

> **"¿Qué decisión debo tomar HOY en el portfolio?"**

Hoy el HTML te muestra mucho **qué pasó** (returns, contributions, race vs benchmark) pero poco **qué hacer ahora**. Las propuestas se enfocan en cerrar ese gap.

---

## 📊 QUICK WINS (alto impacto, ~1h c/u)

### 1. **Decision Center — "Acción del día" tab**
Una pestaña que junta TODAS las señales actionables:

- 🔴 Funds con alpha negativo > 3 meses consecutivos (señal de rotar)
- 🟢 Funds que justifican estar (alpha positivo sostenido)
- 🟡 Funds con cambio de tendencia reciente (deterioro/mejora)
- 📋 Acciones sugeridas con tamaño de trade

**Por qué importa:** Hoy hay que mirar 10 tabs para detectar problemas. Concentrarlo en 1 vista.

### 2. **Rolling Alpha Trends**
Gráfico de **3M rolling alpha** por holding vs ACWI. Línea por fondo.

- Detecta deterioro EARLY (no esperar a SI alpha de -15pp)
- Identifica timing óptimo de rotación
- Visualiza qué funds "están corriendo" actualmente

### 3. **Net Alpha = Alpha − TER**
Columna adicional en Holding Contributions:

```
Alpha bruto: -8% (vs ACWI)
TER:         0.75%
Net Alpha:   -8.75%  ← lo que REALMENTE perdés vs ACWI ETF (que cuesta 0.07%)
```

**Por qué importa:** Justifica (o no) el costo de cada fondo activo.

### 4. **Reglas automatizadas con alertas**
Sistema simple de reglas:
- Si Alpha > -5pp SI **Y** > 6 meses held → Flag "REVIEW"
- Si Alpha < -10pp SI → Flag "CANDIDATE TO CLOSE"
- Si fund missing 3+ holdings de ACWI top 10 → Flag "BENCHMARK MISMATCH"

Muestra un dot rojo/amarillo/verde al lado de cada fund.

---

## 📈 MEDIUM EFFORT (~3-4h c/u)

### 5. **Trade Simulator — "What-if analyzer"**
Interfaz simple:
```
Sell: [LGLI ____ $XXX,XXX]
Buy:  [ACWI ETF ____ $XXX,XXX]
─────────────────────────────
Impact sobre sleeve alpha SI: +0.45pp
Impact sobre TER total:       -0.67%
Net impact:                   +1.12pp
```

**Por qué importa:** Tomar decisiones simulando antes de ejecutar.

### 6. **Stress Test / Scenario Analyzer**
3 escenarios predefinidos:
- "Crisis 2008": -38% equity, -5% credit
- "Covid Crash": -25% equity en 1 mes
- "Stagflación 2022": -18% equity, -15% bonds

Mostrar el drawdown estimado del BIG sleeve actual en cada uno.

### 7. **Heatmap de Monthly Returns**
Tabla tipo Excel donde:
- Filas = meses
- Columnas = funds
- Color = return (verde positivo, rojo negativo)

Visualiza patrones (¿qué fund cae cuando otros caen? correlaciones).

### 8. **Sleeve-level Alpha Decomposition**
Para cada sleeve mostrar **dónde viene el alpha**:
- Allocation effect (¿estás overweight el sector correcto?)
- Selection effect (¿elegiste bien dentro del sector?)
- Currency effect (¿el USD te ayudó/lastimó?)

Brinson attribution. Diagnóstico claro de problemas.

### 9. **Forward-looking Yield Curve**
Para FI sleeve:
- YTW × peso = ingreso esperado próximos 12m
- Sensitivity a +100bps tasas (duración × peso)
- Default risk per credit quality

---

## 🏗️ BIG REBUILDS (~1+ día)

### 10. **Decision Log / Audit Trail**
Cada trade con:
- Fecha + ticker
- Rationale al momento de la decisión
- Hipótesis
- Outcome 3/6/12 meses después
- "Lessons learned"

Convierte el dashboard en herramienta de mejora continua.

### 11. **Manager Quality Score**
Score por fund manager basado en:
- 3y/5y track record vs benchmark
- Sharpe consistencia
- Up/Down capture asimétrica
- TER vs alpha generado

Ayuda a decidir "¿este manager merece ser parte de BIG?"

### 12. **Mobile-Optimized View**
Versión light del dashboard para revisar desde el celular:
- Solo Overview + Decision Center
- Alertas push (opcional via Slack/email)

### 13. **Auto-Generated Monthly Memo**
Al cierre de cada mes, dashboard genera automáticamente:
- 1 paragraph executive summary
- Performance highlights
- Trade rationale
- Risk metrics
- Sent to Fer + boards

Basado en datos del dashboard + GPT-style text generation.

---

## 🎨 UX / Process Improvements

### 14. **Monthly Cadence Checklist**
Cada mes 1ro, dashboard te muestra:
- ☑ Refresh Pershing positions
- ☑ Refresh PIMCO factsheets
- ☑ Refresh FT.com fund holdings
- ☑ Refresh ACWI holdings
- ☑ Run all scripts
- ☑ Review Decision Center
- ☑ Send factsheet to Fer

Checklist visual + status badges.

### 15. **Tooltip / Explanation everywhere**
Cada métrica con un (?) icon que explica qué es y cómo se calcula. Educativo para users nuevos (Fer, asesores).

### 16. **Color-coded Tabs por status**
Si un tab tiene problemas detectados, el tab tiene un dot rojo en la nav. Si todo OK, verde.

---

## 🎯 PRIORIDADES SUGERIDAS

**Top 3 que recomiendo arrancar pronto:**

1. **Decision Center tab** (Quick Win #1) — concentra TODAS las señales actionables en 1 vista
2. **Rolling Alpha Trends** (Quick Win #2) — detecta deterioro EARLY antes de que sea -15pp
3. **Net Alpha after TER** (Quick Win #3) — agrega una columna chiquita pero crítica

Después en orden:
4. Trade Simulator (medium)
5. Reglas automatizadas con alertas (quick)
6. Heatmap monthly returns (medium)

---

## 💭 Preguntas para discutir con Lucas

1. ¿Qué decisión te gustaría poder tomar mirando el dashboard 5 minutos, que hoy te lleva más tiempo?
2. ¿Hay algún insight que descubriste manualmente este mes que el dashboard debería mostrar automático?
3. ¿Qué métrica usás (mentalmente) para decidir "rotar este fund"? Podemos automatizarla.
4. ¿Compartís el dashboard con alguien más (Fer)? ¿Qué vista necesita esa persona?
5. ¿Te molesta algo del UX actual (lento, confuso, muy técnico)?

---

**Last update:** 2026-05-12
**Next review:** Mañana con Lucas
