# Restricciones del reto — evidencia recabada

Fuente: agente **Guía del reto** y el formulario **Agentes → Añadir un agente** de la
plataforma del Reto IA Banorte (`https://hackathon-2024.com/reto-ia`), consultados el
2026-09-11. Las respuestas del agente Guía son citas de lo que respondió; el formulario es
evidencia directa del contrato de integración y pesa más que la conversación.

## 1. El contrato de integración (evidencia directa del formulario)

El formulario de registro define exactamente lo que la plataforma va a hacer con el endpoint:

| Campo | Valor / nota |
|---|---|
| Importar desde tarjeta de agente | `https://<host>/.well-known/agent-card.json` — tarjeta A2A; autocompleta el formulario, incluida la URL base. **Opcional.** |
| Nombre | Requerido. |
| Descripción | Opcional. |
| **URL base** | Requerido. La ayuda dice literalmente: *"Requests go to `{base URL}/responses`"*. Ejemplo mostrado: `https://my-agent.example.com/v1`. |
| **Clave de API** | Opcional. *"Se envía como `Authorization: Bearer …` y se almacena cifrada."* |
| Modelo | Opcional. |
| **Estado de la conversación** | Selector de dos opciones. Por defecto (marcada): **"Reproducir transcripción (sin estado)"**. Alternativa: *"`previous_response_id` (el agente guarda el estado)"*. |
| Entrega de archivos | Selector; valor por defecto "URL de capacidad". |
| Instrucciones | Instrucciones de sistema opcionales enviadas con cada solicitud. |
| Prompt suggestions | Hasta 8, una por línea; se muestran sobre el compositor. |
| Extra request parameters (JSON) | Ejemplo mostrado: `{"temperature": 0.7, "reasoning": {"effort": "medium"}}`. |
| Entrada de imágenes / Entrada de archivos | Toggles, desactivados por defecto. |

### Consecuencias de diseño

1. **La ruta es `POST /v1/responses`** si registramos la URL base como `https://<host>/v1`.
2. **Autenticación: `Authorization: Bearer <clave>`.** Se valida *fail-closed*.
3. **Modo sin estado por defecto.** La plataforma reenvía la transcripción completa en `input`
   en cada turno. **No necesitamos persistir conversaciones ni implementar
   `previous_response_id`** para el flujo por defecto. Esto elimina la tabla `response`, el
   estado en Redis y toda la lógica de continuidad que el plan original contemplaba.
4. **La tarjeta A2A `/.well-known/agent-card.json` es barata y de alto valor**: convierte el
   registro en un solo clic y es un punto demostrable en la defensa técnica.
5. El agente debe tolerar `instructions` y parámetros extra en el cuerpo sin romperse.

## 2. Lo que el agente Guía confirmó

- **Despliegue: opción libre.** *"No hay una plataforma, proveedor cloud, arquitectura ni
  tecnología específica definida como requisito."* Contenedores, serverless, servicios
  administrados o arquitectura distribuida son todos aceptables; lo que importa es poder
  justificar la elección y sus trade-offs (costo, escalabilidad, seguridad, mantenibilidad).
- **SSE no está confirmado como obligatorio.** *"No está especificado que SSE sea obligatorio,
  ni se define una versión concreta de Open Responses que debas implementar."* Su recomendación
  explícita: *"Implementa primero el camino no-streaming, porque es más sencillo de probar y
  depurar."*
- **No hay entregable diferenciado por seniority.** *"No se ha definido un entregable distinto
  para perfiles Senior y Junior."* El nivel se refleja en la profundidad y el criterio de las
  decisiones técnicas, no en requisitos distintos.
- **Cómo se prueba el agente:** que responda de forma natural y consistente sobre el CV, que
  mantenga contexto en preguntas de seguimiento, que explique proyectos y habilidades **sin
  inventar información**, que la solución se pueda construir/integrar/desplegar/operar de
  verdad, y que las decisiones técnicas sean pertinentes y estén justificadas.
- **Casos de prueba que recomienda:** preguntas generales, preguntas específicas de proyecto,
  comparaciones entre habilidades o tecnologías, preguntas de seguimiento con contexto, y
  **solicitudes sobre temas fuera del perfil para comprobar honestidad y límites adecuados.**
- **Evidencia que conviene preparar:** cómo se accede al agente, cómo se configura la
  información del perfil, cómo se manejan errores y preguntas fuera del CV, cómo se
  monitorearía, y qué trade-offs tienen las decisiones tomadas.

## 3. Lo que NO está especificado

El agente Guía respondió explícitamente "no está especificado" a todo esto. No debemos
inventarlo ni asumirlo:

- Rúbrica formal de evaluación.
- **Fecha límite de entrega.**
- **Formato y duración de la demostración** (en vivo, grabada o presentación).
- Casos de prueba concretos o protocolo exacto de evaluación.
- Versión concreta de la especificación de Open Responses.
- Requisitos específicos del material de entrega.

> **Acción pendiente para Adrián:** confirmar fecha límite y formato de demo por el canal
> oficial de reclutamiento, no por el agente Guía.

## 4. Dato de contexto

El propio agente Guía del reto está desplegado en **Azure Container Apps**
(`https://reto-ia-agent.calmrock-f65cc26b.eastus.azurecontainerapps.io`). Es una referencia de
que esperan un contenedor con un endpoint HTTP público, no un requisito de plataforma.
