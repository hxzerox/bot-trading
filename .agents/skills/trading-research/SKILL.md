---
name: trading-research
description: Usar al explorar, explicar, comparar o revisar estrategias, datos de mercado de cripto o acciones, backtests o paper trading. No usar para colocar órdenes reales.
---

# Investigación de trading

## Objetivo

Producir análisis claro y reproducible. Separa observaciones de supuestos y nunca presentes un backtest como promesa de resultados futuros.

## Lista de revisión

- Identifica la fuente de datos, el activo, el intervalo, el periodo, la zona horaria y el tratamiento de datos faltantes.
- Comprueba si se eligió la estrategia usando los mismos datos con los que se muestran los resultados. Prefiere periodos fuera de muestra y análisis walk-forward.
- Incluye comisiones, diferencial, deslizamiento, liquidez y costos de financiación o préstamo cuando corresponda.
- Compara con una referencia sencilla, como comprar y mantener, y una alternativa en efectivo.
- Informa número de operaciones, exposición, drawdown, volatilidad e incertidumbre además del rendimiento. Las muestras pequeñas no permiten conclusiones firmes.
- Busca sesgo de supervivencia, filtración de información futura, demasiadas búsquedas de parámetros y selección sesgada de datos.
- Explica los supuestos y cómo reproducir los cálculos. No ocultes activos con pérdidas ni periodos sin actividad.

## Reglas de seguridad

- Usa por defecto análisis de solo lectura, backtesting o paper trading.
- No llames endpoints de órdenes reales, no pidas frases semilla y no pongas secretos en archivos, registros o informes.
- No supongas que un porcentaje de riesgo de un experimento anterior es apropiado. Expón el tamaño de posición y los límites de pérdida para revisión.
- Trata la ejecución real como una decisión separada que requiere controles de riesgo independientes y confirmación humana explícita.
- Di claramente cuando los datos no bastan. No declares rentable una estrategia basándote solo en un resultado dentro de muestra.
