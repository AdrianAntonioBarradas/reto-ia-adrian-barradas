"""The four CV tools.

Kept deliberately small. A wide tool surface invites the model to improvise; four
tools with clear boundaries make its behaviour predictable and its failures
diagnosable.

``list_skills`` always returns the proficiency tag alongside every skill. That is not
a convenience — it is the mechanism that stops a LEARNING entry from being handed to
the model as a bare skill name it could present as expertise.
"""

from __future__ import annotations

from typing import Any

from app.knowledge.corpus import Corpus
from app.llm.base import ToolSpec
from app.retrieval.engine import RetrievalEngine
from app.tools.base import Tool, ToolResult

MAX_SEARCH_RESULTS = 8


def _skill_payload(skill: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "nombre": skill.name,
        "nivel": skill.proficiency,
        "categoria": skill.category_label,
        "dominios": list(skill.domains),
    }
    if skill.note:
        payload["detalle"] = skill.note
    return payload


def build_tools(corpus: Corpus, engine: RetrievalEngine) -> list[Tool]:
    # ------------------------------------------------------------------ #
    def get_profile() -> ToolResult:
        profile = corpus.profile
        return ToolResult(
            data={
                "nombre": profile["name"],
                "titular": profile.get("headline"),
                "ubicacion": profile.get("location"),
                "correo": profile.get("email"),
                "idiomas": profile.get("languages", []),
                "resumenes": [
                    {"enfoque": s["label"], "texto": s["es"]} for s in profile.get("summaries", [])
                ],
                "fortalezas": profile.get("strengths", []),
                "educacion": [
                    {
                        "institucion": e["institution"],
                        "titulo": e["degree_es"],
                        "anios": e["years"],
                        "estatus": e.get("status_es"),
                        "promedio": e.get("gpa"),
                    }
                    for e in corpus.education
                ],
            },
            evidence_ids=("profile#headline", "profile#summaries", "education"),
        )

    # ------------------------------------------------------------------ #
    def search_experience(query: str, top_k: int = 5) -> ToolResult:
        limit = max(1, min(int(top_k), MAX_SEARCH_RESULTS))
        results = engine.search(query, top_k=limit)
        return ToolResult(
            data={
                "consulta": query,
                "modo_recuperacion": engine.mode,
                "resultados": [
                    {
                        "fuente": r.source_id,
                        "tipo": r.chunk.entity_type,
                        "texto": r.chunk.text,
                        "recuperadores": list(r.retrievers),
                    }
                    for r in results
                ],
            },
            evidence_ids=tuple(r.source_id for r in results),
        )

    # ------------------------------------------------------------------ #
    def get_project(project_id: str) -> ToolResult:
        project = corpus.project(project_id)
        if project is None:
            # An unknown id is a normal outcome, not an exception: the model
            # guessed, and the honest result is the list of real options.
            return ToolResult(
                data={
                    "error": "proyecto_no_encontrado",
                    "proyectos_disponibles": [
                        {"id": p["id"], "nombre": p["name"]} for p in corpus.projects
                    ],
                }
            )
        payload = {k: v for k, v in project.items() if k != "id"}
        payload["id"] = project["id"]
        return ToolResult(data=payload, evidence_ids=(f"projects#{project['id']}",))

    # ------------------------------------------------------------------ #
    def list_skills(category: str | None = None, domain: str | None = None) -> ToolResult:
        skills = list(corpus.skills)
        if category:
            wanted = category.strip().lower()
            skills = [
                s
                for s in skills
                if s.category.lower() == wanted or s.category_label.lower() == wanted
            ]
        if domain:
            wanted_domain = domain.strip().lower()
            skills = [s for s in skills if wanted_domain in [d.lower() for d in s.domains]]

        # Strongest first, so the model sees proven work before it sees aspirations.
        skills.sort(key=lambda s: (-s.rank, s.name))
        return ToolResult(
            data={
                "categorias_disponibles": list(corpus.skill_categories),
                "total": len(skills),
                "leyenda_niveles": {
                    "PROVEN": "experiencia profesional en producción",
                    "EXPERIENCED": "conocimiento sólido, no experto",
                    "PROJECT": "sólo en proyectos personales o académicos",
                    "FAMILIAR": "sólo familiaridad, NO es experiencia",
                    "LEARNING": "lo está aprendiendo, NO tiene experiencia",
                },
                "habilidades": [_skill_payload(s) for s in skills],
            },
            evidence_ids=("skills",),
        )

    categories = list(corpus.skill_categories)

    return [
        Tool(
            spec=ToolSpec(
                name="get_profile",
                description=(
                    "Datos canónicos del perfil: nombre, titular, ubicación, correo, idiomas, "
                    "resúmenes profesionales por enfoque, fortalezas y educación. Úsala para "
                    "preguntas generales sobre quién es o qué estudió."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            handler=get_profile,
        ),
        Tool(
            spec=ToolSpec(
                name="search_experience",
                description=(
                    "Busca en la experiencia, los proyectos y las habilidades por significado y "
                    "por término exacto. Es la herramienta principal: úsala para cualquier "
                    "pregunta sobre qué hizo, dónde, con qué tecnología o con qué resultado."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La pregunta o los términos a buscar, en español.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": f"Cuántos resultados devolver (1-{MAX_SEARCH_RESULTS}).",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=search_experience,
        ),
        Tool(
            spec=ToolSpec(
                name="get_project",
                description=(
                    "Detalle estructurado de un proyecto, incluida su AUTORÍA (own = suyo, "
                    "contribution = contribuyó a un producto de terceros, not_mine = no es suyo). "
                    "Consulta siempre la autoría antes de atribuirle un proyecto."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "Identificador del proyecto.",
                            "enum": [p["id"] for p in corpus.projects],
                        }
                    },
                    "required": ["project_id"],
                },
            ),
            handler=get_project,
        ),
        Tool(
            spec=ToolSpec(
                name="list_skills",
                description=(
                    "Lista habilidades con su NIVEL REAL de dominio. Úsala siempre antes de "
                    "afirmar que sabe o no sabe una tecnología: el nivel distingue experiencia "
                    "profesional de familiaridad y de temas que apenas está aprendiendo."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Categoría a filtrar.",
                            "enum": categories,
                        },
                        "domain": {
                            "type": "string",
                            "description": "Dominio a filtrar, por ejemplo ai, backend, data.",
                        },
                    },
                },
            ),
            handler=list_skills,
        ),
    ]
