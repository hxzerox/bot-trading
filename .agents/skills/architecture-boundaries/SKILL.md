---
name: architecture-boundaries
description: Usar al planear o cambiar este proyecto, añadir una integración de mercado, bróker, chat, voz o domótica, o decidir dónde debe vivir el código.
---

# Límites de arquitectura

## Mantén el diseño entendible

- Separa conversación del asistente, adaptadores de canales, conectores, reglas de dominio, investigación de mercado, controles de riesgo, ejecución y almacenamiento.
- Define interfaces pequeñas para los servicios externos, así podrás cambiar un proveedor sin rehacer la lógica de estrategias.
- Normaliza los datos externos en los límites de cada conector y valídalos antes de usarlos.
- Mantén credenciales y llamadas de red fuera de los módulos que calculan estrategias.
- Configura la ejecución de órdenes como un servicio separado; usa solo lectura o simulación por defecto.
- Registra las acciones importantes y la aprobación correspondiente en una bitácora.

## Cambios en el repositorio

- Revisa las convenciones existentes antes de añadir carpetas, dependencias o flujos de trabajo.
- Prefiere un cambio pequeño y completo a una reescritura amplia o a añadir frameworks sin necesidad.
- Documenta los servicios externos nuevos, su configuración y qué pasa cuando fallan.
- No añadas secretos, flujos automáticos de trading real ni despliegues desatendidos.
- Mantén este laboratorio de investigación separado del futuro servicio Jarvis. Conéctalos mediante una interfaz, sin acoplar el asistente a la lógica interna de estrategias.
