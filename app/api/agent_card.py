"""A2A agent card at ``/.well-known/agent-card.json``.

The Reto IA registration form accepts a card URL and auto-fills the whole form
from it. Serving one turns registration into a single paste, and it makes the
agent *discoverable* rather than merely callable.
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
        "protocolVersion": "0.3.0",
        "name": settings.agent_name,
        "description": _DESCRIPTION,
        "url": f"{base}/v1",
        "preferredTransport": "JSONRPC",
        "version": "0.1.0",
        "provider": {"organization": "Adrián Barradas", "url": base},
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "Clave de API del agente.",
            }
        },
        "security": [{"bearer": []}],
        "skills": _SKILLS,
    }
