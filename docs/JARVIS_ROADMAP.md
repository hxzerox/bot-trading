# Hoja de ruta de Jarvis: voz, domótica, chats y mercados

Este documento prepara el proyecto para instalarlo más adelante en un equipo dedicado. GitHub guarda el código, las skills y la documentación; no ejecuta el asistente por sí mismo. Añadir estos archivos no instala programas ni paquetes.

## Mantener las funciones separadas

Este repositorio debe seguir siendo el laboratorio de investigación y simulación de estrategias. Jarvis debería ser un servicio independiente que consulte datos aprobados y solicite informes al laboratorio. El agente conversacional no debe importar directamente el motor de estrategias ni guardar credenciales de exchanges o brókers.

Estructura posible para el repositorio futuro de Jarvis:

```text
jarvis/
  api/                   # interfaces HTTP y validación
  assistant/             # conversación y coordinación
  channels/              # voz y adaptadores de chat
  connectors/            # MCP, Home Assistant, mercado y brókers
  domain/                # reglas y modelos compartidos
  trading/
    market_data/         # datos normalizados
    research/            # backtests y análisis
    risk/                # límites y validación previa
    execution/           # primero simulación; aislada del agente
  storage/               # historial y persistencia
  observability/         # registros, métricas y auditoría
  .agents/skills/        # instrucciones del agente para este proyecto
```

## Componentes candidatos

Elige solo lo necesario para la primera versión funcional. Antes de adoptar una dependencia, comprueba su mantenimiento, licencia, seguridad y disponibilidad en tu país.

| Necesidad | Opción | Comentario |
|---|---|---|
| Voz y domótica | [Home Assistant](https://github.com/home-assistant/core) + [Assist](https://www.home-assistant.io/voice_control/) | Buen punto de partida para controlar el hogar y usar voz local. |
| Asistente personal con chats | [OpenClaw](https://github.com/openclaw/openclaw) | Admite muchos canales; revisa cada permiso y herramienta antes de activarlos. |
| Agente propio en Python | [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Herramientas, traspasos, guardrails, sesiones y voz. |
| Flujos de agente con estado | [LangGraph](https://github.com/langchain-ai/langgraph) | Útil para flujos que necesitan guardar y reanudar su estado. |
| Conectores de aplicaciones | [MCP Registry](https://github.com/modelcontextprotocol/registry), [FastMCP](https://github.com/PrefectHQ/fastmcp), [Composio](https://github.com/ComposioHQ/composio) | Revisa quién mantiene cada conector, su código, permisos y manejo de secretos. |
| Automatización visual | [n8n](https://github.com/n8n-io/n8n) | Conecta APIs y aplicaciones; se puede autoalojar. |
| APIs de exchanges de cripto | [CCXT](https://github.com/ccxt/ccxt) | API unificada; empieza con permisos de solo lectura o simulación. |
| Investigación de estrategias cripto | [Freqtrade](https://github.com/freqtrade/freqtrade) o [Hummingbot](https://github.com/hummingbot/hummingbot) | Haz backtesting o paper trading antes de considerar operaciones reales. |
| Investigación multimercado | [LEAN](https://github.com/QuantConnect/Lean) o [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Revisa los requisitos de datos y bróker para tu mercado. |
| Conexión a bróker de acciones | [Alpaca-py](https://github.com/alpacahq/alpaca-py) o [ib_async](https://github.com/ib-api-reloaded/ib_async) | Confirma que el bróker, los activos y la API estén disponibles para ti. |
| Bots de chat | [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot), [aiogram](https://github.com/aiogram/aiogram), [discord.py](https://github.com/Rapptz/discord.py) | Usa las APIs oficiales y tokens con permisos mínimos. |

## Etapas sugeridas

1. Decide qué funciones se ejecutarán localmente en el equipo dedicado y cuáles usarán APIs alojadas.
2. Crea un asistente de solo lectura para resumir mercados y consultar el estado de dispositivos del hogar.
3. Añade un canal de chat y una integración de voz con Home Assistant.
4. Añade datos de mercado e informes; no conectes la ejecución de órdenes al agente.
5. Valida estrategias con comisiones, deslizamiento, periodos fuera de muestra, drawdown y suficientes operaciones.
6. Añade paper trading con un interruptor de emergencia y registro de auditoría.
7. Solo si más adelante se decide por separado, añade ejecución real detrás de límites de riesgo independientes y confirmación humana.

## Seguridad y controles de trading

- Guarda secretos en el administrador de credenciales del equipo de destino o en su configuración de entorno; nunca en Git.
- Usa credenciales separadas y los permisos mínimos. Desactiva retiros en claves de exchanges.
- Trata mensajes, documentos y respuestas de conectores como datos externos, no como instrucciones para cambiar permisos.
- Exige confirmación humana antes de enviar mensajes, cambiar dispositivos sensibles o colocar órdenes.
- Registra las acciones y su aprobación, sin guardar los valores secretos.
- Los backtests y resultados simulados no garantizan ganancias. [STATUS.md](../STATUS.md) describe los límites de los experimentos actuales de este repositorio.
