# Bot Trading

Laboratorio de investigación y simulación de estrategias para criptomonedas. El estado actual y las notas de evaluación fuera de muestra están en [STATUS.md](STATUS.md).

## Alcance

Este repositorio se usa para investigar y simular. Los resultados publicados no demuestran rendimientos futuros ni son una recomendación de trading en vivo. Revisa las limitaciones y el tamaño de las muestras en STATUS.md antes de sacar conclusiones.

La idea de Jarvis (voz, domótica, chats, cripto y acciones) está documentada aparte en [docs/JARVIS_ROADMAP.md](docs/JARVIS_ROADMAP.md). El asistente futuro debe ser un servicio separado del código de estrategias; no debe tener acceso directo a claves de exchanges ni a la ejecución de órdenes.

## Archivos principales

- `bot.py`: punto de entrada del bot actual.
- `research.py`: investigación de estrategias.
- `STATUS.md`: estado de los experimentos y sus limitaciones.
- `champion.json`, `forward.json`, `auto_stats.json`: datos generados por experimentos.

## Principios de seguridad

- Mantén los experimentos en simulación o paper trading.
- No subas claves API, tokens, datos privados de cuentas ni otros secretos a Git.
- Un modelo puede explicar una señal, pero una capa de riesgo independiente debe validar cualquier orden futura.
- Nunca des permisos de retiro de fondos a un asistente.
