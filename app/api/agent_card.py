"""A2A agent card at ``/.well-known/agent-card.json``.

The Reto IA registration form accepts a card URL and auto-fills the whole form from
it, so serving one turns registration into a single paste and makes the agent
*discoverable* rather than merely callable.

**This agent is not an A2A agent.** It speaks Open Responses over HTTP, and the card
is used purely for discovery. That is why ``protocolBinding`` is ``HTTP+JSON`` rather
than ``JSONRPC``: the card should describe what is actually there.

Shape matters here, and the first version of this file got it wrong. A2A v1.0 replaced
the single top-level ``url``/``preferredTransport`` pair with **``supportedInterfaces``**
— a list of ``AgentInterface`` entries, each with its own url, binding and protocol
version, so one agent can expose the same capability over several bindings. The
platform rejected the old shape outright with "falta name o supportedInterfaces".

JSON is camelCase (``supportedInterfaces``, ``securityRequirements``) even though the
normative protobuf is snake_case.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()

_DESCRIPTION = (
    "Agente conversacional sobre la trayectoria profesional de Adrián Barradas: "
    "perfil, experiencia, habilidades y proyectos. Responde con evidencia del "
    "perfil y se abstiene cuando no la tiene."
)

_SKILLS: list[dict[str, Any]] = [
    {
        "id": "perfil",
        "name": "Perfil profesional",
        "description": "Resumen del perfil, formación e idiomas.",
        "tags": ["cv", "perfil"],
        "examples": ["¿Cuál es su perfil profesional?", "¿Qué estudió?"],
    },
    {
        "id": "experiencia",
        "name": "Experiencia",
        "description": "Roles, responsabilidades y logros con fechas y contexto.",
        "tags": ["cv", "experiencia"],
        "examples": ["¿Qué hizo en Cicada?", "¿Cuánta experiencia tiene en fintech?"],
    },
    {
        "id": "habilidades",
        "name": "Habilidades",
        "description": (
            "Tecnologías y nivel de dominio real, distinguiendo experiencia "
            "profesional de familiaridad y de temas en aprendizaje."
        ),
        "tags": ["cv", "habilidades"],
        "examples": ["¿Qué tan fuerte es en Go?", "¿Tiene experiencia con Kubernetes?"],
    },
    {
        "id": "proyectos",
        "name": "Proyectos",
        "description": "Proyectos propios y contribuciones, con la autoría explícita.",
        "tags": ["cv", "proyectos"],
        "examples": ["Cuéntame del framework de evaluación de chatbots."],
    },
]


@router.get("/.well-known/agent-card.json")
async def agent_card() -> dict[str, Any]:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    return {
        "name": settings.agent_name,
        "description": _DESCRIPTION,
        "version": "1.0.0",
        "documentationUrl": "https://github.com/AdrianAntonioBarradas/reto-ia-adrian-barradas",
        "provider": {"organization": "Adrián Barradas", "url": base},
        # One entry: this agent exposes Open Responses over plain HTTP. Listing it as
        # JSONRPC would be a claim the endpoint does not honour.
        "supportedInterfaces": [
            {
                "url": f"{base}/v1",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "securitySchemes": {
            "bearer": {
                "httpAuthSecurityScheme": {
                    "scheme": "bearer",
                    "description": "Clave de API del agente.",
                }
            }
        },
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "skills": _SKILLS,
    }
