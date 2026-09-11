"""Turn the canonical corpus into retrievable chunks.

Chunking is a retrieval-quality decision, not a storage optimisation, so this is
hand-written rather than a token-window splitter:

* **Semantic units.** One role highlight, one project, one skill category, one
  education entry. A CV has natural boundaries and cutting across them produces
  fragments that retrieve well and read badly.
* **Self-contained text.** Every chunk names its own subject. "Redujo la carga
  operativa manual" is useless out of context; "Cicada — automatización de
  liquidación: redujo la carga operativa manual" answers a question on its own.
* **A context prefix before embedding.** Each chunk is embedded with a short line
  naming the document and entity it came from. This is the cheap form of contextual
  retrieval, and at this corpus size it costs nothing.

The chunk carries its metadata — proficiency, attribution, domains — because the
answer policy needs them at generation time, not just at ranking time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.knowledge.corpus import Corpus


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    text: str
    entity_type: str
    entity_id: str
    source_id: str
    context_prefix: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def embedding_text(self) -> str:
        """What actually gets embedded: the prefix restores the lost context."""
        return f"{self.context_prefix}\n{self.text}".strip() if self.context_prefix else self.text


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _profile_chunks(corpus: Corpus) -> list[Chunk]:
    chunks: list[Chunk] = []
    profile = corpus.profile

    headline = _clean(profile.get("headline"))
    if headline:
        chunks.append(
            Chunk(
                id="profile:headline",
                text=f"Perfil profesional de {profile['name']}: {headline}",
                entity_type="profile",
                entity_id="headline",
                source_id="profile#headline",
                context_prefix="Perfil general",
            )
        )

    for summary in profile.get("summaries", []):
        text = _clean(summary.get("es"))
        chunks.append(
            Chunk(
                id=f"profile:summary:{summary['id']}",
                text=f"Posicionamiento como {summary['label']}: {text}",
                entity_type="profile",
                entity_id=f"summary:{summary['id']}",
                source_id="profile#summaries",
                context_prefix=f"Resumen profesional — {summary['label']}",
                metadata={"positioning": summary["id"]},
            )
        )

    languages = ", ".join(
        f"{lang['name']} ({lang['level']})" for lang in profile.get("languages", [])
    )
    if languages:
        chunks.append(
            Chunk(
                id="profile:languages",
                text=f"Idiomas que habla {profile['name']}: {languages}.",
                entity_type="profile",
                entity_id="languages",
                source_id="profile#languages",
                context_prefix="Idiomas",
            )
        )

    strengths = profile.get("strengths", [])
    if strengths:
        body = " ".join(f"- {_clean(s)}" for s in strengths)
        chunks.append(
            Chunk(
                id="profile:strengths",
                text=f"Principales fortalezas profesionales: {body}",
                entity_type="profile",
                entity_id="strengths",
                source_id="profile#strengths",
                context_prefix="Fortalezas",
            )
        )

    style = profile.get("working_style", [])
    if style:
        body = " ".join(f"- {_clean(s)}" for s in style)
        chunks.append(
            Chunk(
                id="profile:working_style",
                text=f"Forma de trabajar: {body}",
                entity_type="profile",
                entity_id="working_style",
                source_id="profile#working_style",
                context_prefix="Estilo de trabajo",
            )
        )
    return chunks


def _education_chunks(corpus: Corpus) -> list[Chunk]:
    chunks: list[Chunk] = []
    for entry in corpus.education:
        parts = [f"{entry['institution']} ({entry['years']}): {entry['degree_es']}."]
        if entry.get("gpa"):
            parts.append(f"Promedio {entry['gpa']}.")
        if entry.get("status_es"):
            parts.append(f"Estatus: {entry['status_es']}.")
        if entry.get("foundation"):
            parts.append("Áreas: " + "; ".join(entry["foundation"]) + ".")
        if entry.get("note"):
            parts.append(_clean(entry["note"]))
        chunks.append(
            Chunk(
                id=f"education:{entry['id']}",
                text="Formación académica. " + " ".join(parts),
                entity_type="education",
                entity_id=entry["id"],
                source_id=f"education#{entry['id']}",
                context_prefix="Educación",
            )
        )
    return chunks


def _experience_chunks(corpus: Corpus) -> list[Chunk]:
    chunks: list[Chunk] = []
    for entry in corpus.experience:
        org = entry["organization"]
        role = entry.get("role_es", "")
        period = f"{entry.get('start_date', '?')} a {entry.get('end_date') or 'actualidad'}"
        header = f"{org} — {role} ({period})"

        overview = [f"{header}. Sector: {entry.get('sector', 'n/d')}."]
        if entry.get("domain"):
            overview.append(f"Dominio: {_clean(entry['domain'])}")
        if entry.get("technologies"):
            overview.append("Tecnologías: " + ", ".join(entry["technologies"]) + ".")
        if entry.get("presentation_rule"):
            overview.append(f"Nota de presentación: {_clean(entry['presentation_rule'])}")
        chunks.append(
            Chunk(
                id=f"experience:{entry['id']}:overview",
                text=" ".join(overview),
                entity_type="experience",
                entity_id=entry["id"],
                source_id=f"experience#{entry['id']}",
                context_prefix=f"Experiencia profesional — {org}",
                metadata={"organization": org, "role": role, "period": period},
            )
        )

        for highlight in entry.get("highlights", []):
            body = _clean(highlight.get("es"))
            text = f"{header}. {body}"
            if highlight.get("caveat"):
                # The caveat travels with the claim. Retrieving the achievement
                # without its qualifier is precisely how a FAMILIAR skill gets
                # spoken about as expertise.
                text += f" MATIZ IMPORTANTE: {_clean(highlight['caveat'])}"
            chunks.append(
                Chunk(
                    id=f"experience:{entry['id']}:{highlight['id']}",
                    text=text,
                    entity_type="experience_highlight",
                    entity_id=f"{entry['id']}.{highlight['id']}",
                    source_id=f"experience#{entry['id']}.{highlight['id']}",
                    context_prefix=f"Logro en {org} — {role}",
                    metadata={
                        "organization": org,
                        "proficiency": highlight.get("proficiency"),
                        "domains": highlight.get("domains", []),
                        "has_caveat": bool(highlight.get("caveat")),
                    },
                )
            )
    return chunks


def _project_chunks(corpus: Corpus) -> list[Chunk]:
    chunks: list[Chunk] = []
    for project in corpus.projects:
        name = project["name"]
        attribution = project.get("attribution", "own")

        parts = [f"Proyecto: {name}."]
        if project.get("context"):
            parts.append(f"Contexto: {_clean(project['context'])}")
        if project.get("problem"):
            parts.append(f"Problema: {_clean(project['problem'])}")
        if project.get("solution"):
            parts.append(f"Solución: {_clean(project['solution'])}")
        if project.get("contribution"):
            parts.append(f"Su contribución: {_clean(project['contribution'])}")
        if project.get("impact"):
            parts.append(f"Resultado: {_clean(project['impact'])}")
        if project.get("technologies"):
            parts.append("Tecnologías: " + ", ".join(project["technologies"]) + ".")
        if project.get("why_it_matters"):
            parts.append(f"Por qué importa: {_clean(project['why_it_matters'])}")

        # Attribution is stated inside the retrievable text, not only in metadata,
        # so it reaches the model even if it only ever sees the chunk body.
        if attribution == "not_mine":
            parts.append(
                f"AUTORÍA: esto NO lo construyó Adrián. {_clean(project.get('attribution_note'))}"
            )
        elif attribution == "contribution":
            parts.append(
                "AUTORÍA: contribución a un producto de terceros, no es suyo. "
                + _clean(project.get("attribution_note"))
            )

        chunks.append(
            Chunk(
                id=f"project:{project['id']}",
                text=" ".join(p for p in parts if p.strip()),
                entity_type="project",
                entity_id=project["id"],
                source_id=f"projects#{project['id']}",
                context_prefix=f"Proyecto — {name}",
                metadata={
                    "attribution": attribution,
                    "proficiency": project.get("proficiency"),
                    "domains": project.get("domains", []),
                },
            )
        )
    return chunks


# How each proficiency tag reads as a sentence. Rendering this into the chunk text
# means the honest phrasing is *retrieved*, not left for the model to infer from a
# bare tag it may or may not respect.
PROFICIENCY_SENTENCE = {
    "PROVEN": "Tiene experiencia profesional en producción con esto; es una de sus especialidades.",
    "EXPERIENCED": (
        "Tiene conocimiento sólido y ha trabajado con esto, pero no es experto ni es su "
        "especialidad principal."
    ),
    "FAMILIAR": (
        "Sólo tiene familiaridad con esto. NO es experiencia profesional y NO debe "
        "presentarse como experiencia ni como dominio."
    ),
    "LEARNING": (
        "Lo está APRENDIENDO actualmente. NO tiene experiencia profesional con esto y NO "
        "ha trabajado con esto en producción. La respuesta honesta a '¿tiene experiencia "
        "en esto?' es NO."
    ),
    "PROJECT": (
        "Lo ha usado únicamente en proyectos personales o académicos, no en trabajo "
        "profesional remunerado."
    ),
}


def _skill_detail_chunks(corpus: Corpus) -> list[Chunk]:
    """One chunk per individual skill.

    Category-level chunks alone are too coarse. A question about a single technology
    has to compete against a chunk that is mostly about twenty other technologies,
    and the evaluation caught exactly that: "¿ha trabajado con Kubernetes en
    producción?" retrieved a chunk about a *production bot* instead, because the
    incidental word "producción" outweighed the one term that mattered.

    A dedicated chunk per skill gives every technology its own retrievable
    statement, with the honest phrasing already written into it. The category chunks
    are kept as well, for questions that ask about a whole area.
    """
    chunks: list[Chunk] = []
    for skill in corpus.skills:
        sentence = PROFICIENCY_SENTENCE.get(skill.proficiency, "")
        parts = [f"{skill.name} — nivel {skill.proficiency}. {sentence}"]
        if skill.note:
            parts.append(f"Detalle: {_clean(skill.note)}")
        parts.append(f"Categoría: {skill.category_label}.")
        chunks.append(
            Chunk(
                id=f"skill:{skill.category}:{skill.name}",
                text=" ".join(parts),
                entity_type="skill",
                entity_id=skill.name,
                source_id=f"skills#{skill.category}.{skill.name}",
                context_prefix=f"Habilidad — {skill.name}",
                metadata={
                    "skill": skill.name,
                    "proficiency": skill.proficiency,
                    "domains": list(skill.domains),
                    "category": skill.category,
                },
            )
        )
    return chunks


def _skill_chunks(corpus: Corpus) -> list[Chunk]:
    """One chunk per category, with every skill's tag inline.

    Complements the per-skill chunks above: this is what answers "¿qué habilidades
    de IA tiene?", where the useful unit is the whole area rather than one entry.
    """
    chunks: list[Chunk] = []
    for category, label in corpus.skill_categories.items():
        skills = corpus.skills_in_category(category)
        if not skills:
            continue
        rendered = []
        for skill in skills:
            item = f"{skill.name} [{skill.proficiency}]"
            if skill.note:
                item += f" ({_clean(skill.note)})"
            rendered.append(item)
        chunks.append(
            Chunk(
                id=f"skills:{category}",
                text=(
                    f"Habilidades de {label}, cada una con su nivel real de dominio: "
                    + "; ".join(rendered)
                    + "."
                ),
                entity_type="skill_category",
                entity_id=category,
                source_id=f"skills#{category}",
                context_prefix=f"Habilidades — {label}",
                metadata={"category": category, "count": len(skills)},
            )
        )

    domain = corpus.domain_knowledge
    if domain.get("items"):
        chunks.append(
            Chunk(
                id="skills:domain_knowledge",
                text=f"{domain.get('label', 'Conocimiento de dominio')}: "
                + "; ".join(domain["items"])
                + ".",
                entity_type="domain_knowledge",
                entity_id="domain_knowledge",
                source_id="skills#domain_knowledge",
                context_prefix="Conocimiento de dominio",
            )
        )
    return chunks


def _policy_chunks(corpus: Corpus) -> list[Chunk]:
    """Denials are retrievable facts.

    "No tiene experiencia en Azure" has to be findable the same way any other fact
    is. If the only way to answer an Azure question were the absence of evidence,
    the model would be guessing rather than reporting.
    """
    chunks: list[Chunk] = []
    for denial in corpus.policy.get("absolute_denials", []):
        subject = denial["subject"]
        chunks.append(
            Chunk(
                id=f"policy:denial:{subject}",
                text=f"Sobre {subject}: {_clean(denial['answer_es'])}",
                entity_type="denial",
                entity_id=subject,
                source_id=f"policy#absolute_denials.{subject}",
                context_prefix=f"Límite de experiencia — {subject}",
                metadata={"denial": True},
            )
        )
    for denial in corpus.policy.get("attribution_denials", []):
        subject = denial["subject"]
        chunks.append(
            Chunk(
                id=f"policy:attribution:{subject}",
                text=f"Sobre la autoría de {subject}: {_clean(denial['answer_es'])}",
                entity_type="attribution_denial",
                entity_id=subject,
                source_id="policy#attribution_denials",
                context_prefix=f"Autoría — {subject}",
                metadata={"denial": True},
            )
        )
    return chunks


def build_chunks(corpus: Corpus) -> list[Chunk]:
    chunks = [
        *_profile_chunks(corpus),
        *_education_chunks(corpus),
        *_experience_chunks(corpus),
        *_project_chunks(corpus),
        *_skill_chunks(corpus),
        *_skill_detail_chunks(corpus),
        *_policy_chunks(corpus),
    ]
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.id in seen:
            raise ValueError(f"duplicate chunk id: {chunk.id}")
        seen.add(chunk.id)
    return chunks
