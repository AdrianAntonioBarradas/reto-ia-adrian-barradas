"""The policy gate.

Runs before the model, on every turn. Two jobs:

1. **Short-circuit questions that must never reach generation.** Compensation,
   personal contact details, why a job ended, other selection processes. The
   underlying data is absent from the corpus, so the model could not answer these
   correctly even if asked — but letting it try invites it to improvise a plausible
   answer, which is worse than a clean refusal.

2. **Detect instruction-shaped user input.** Not to block it — blocking on keywords
   is trivially evaded and produces false positives on legitimate questions — but to
   mark the turn so the system prompt can restate the boundary and the evaluation can
   assert on it.

The gate is deliberately conservative. A false refusal on a real CV question is a
worse product than a slightly over-broad answer, so patterns are narrow and anchored
to the specific topics the source profile marks as private.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.retrieval.lexical import normalize


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The gate's verdict for one turn."""

    refuse: bool = False
    refusal_text: str | None = None
    topic: str | None = None
    injection_suspected: bool = False


# Topic -> patterns, matched against accent-folded lowercase text. Each entry
# corresponds to an `out_of_scope` block in data/canonical/policy.yaml.
_REFUSAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "compensación": (
        r"\b(cuanto|que)\s+(gana|ganaba|ganas|cobra|cobraba|percibe|percibia)\b",
        r"\b(salario|sueldo|remuneracion|compensacion|aguinaldo|prestaciones)\b",
        r"\bexpectativa[s]?\s+(salarial|economica|de\s+sueldo)\b",
        r"\b(salary|compensation)\b",
    ),
    # These must match a request *for a contact value*, not a mention of a channel.
    # The first version matched the bare word "whatsapp", so the technical question
    # "¿implementó la integración de WhatsApp Business?" was refused as a request for
    # personal contact details. A false refusal on a real CV question is a worse
    # product than a slightly over-broad answer.
    "datos de contacto personales": (
        r"\b(cual\s+es|dame|pasame|comparte(me)?|me\s+das|tienes)\b[^?]{0,40}"
        r"\b(telefono|numero\s+(de\s+)?(telefono|celular|contacto|whatsapp)|celular|movil"
        r"|direccion|domicilio)\b",
        r"\bnumero\s+de\s+(telefono|celular|contacto|whatsapp)\b",
        r"\b(su|tu)\s+(telefono|celular|movil|domicilio|whatsapp)\b",
        r"\b(donde|en\s+que\s+calle)\s+vive\b",
        r"\bphone\s+number\b",
    ),
    "motivos de salida o referencias": (
        r"\bpor\s*que\s+(se\s+fue|salio|dejo|renuncio|lo\s+corrieron|lo\s+despidieron)\b",
        r"\b(lo\s+)?(despidieron|corrieron)\b",
        r"\bmotivo[s]?\s+de\s+(salida|renuncia|baja)\b",
        r"\bwhy\s+did\s+he\s+leave\b",
    ),
    "procesos de selección en curso": (
        r"\b(otros?\s+)?proceso[s]?\s+de\s+seleccion\b",
        r"\b(en\s+que|cuales)\s+(otras?\s+)?vacantes?\b",
        r"\bofertas?\s+(de\s+trabajo\s+)?(que\s+tiene|en\s+curso)\b",
        r"\bentrevistas?\s+(que\s+tiene|en\s+curso|pendientes)\b",
    ),
    "opiniones sobre personas o empresas": (
        r"\bque\s+(opina|piensa|dice)\s+(de|sobre)\s+(sus?\s+)?(ex\s*-?\s*)?(companer|jefe|colega|empresa)",
        r"\bhabla\s+mal\s+de\b",
    ),
}

# Instruction-shaped input. Used as a signal, never as a hard block.
_INJECTION_PATTERNS: tuple[str, ...] = (
    r"\bignora\b.*\b(instruccion|indicacion|regla|anterior|previo)",
    r"\bolvida\b.*\b(instruccion|indicacion|regla|todo)",
    r"\bignore\b.*\b(instruction|previous|above|prior)",
    r"\b(system|sistema)\s*:",
    r"\bnueva\s+directiva\b",
    r"\b(muestra|revela|imprime|dime)\b.*\b(system\s*prompt|prompt\s+del\s+sistema|tus\s+instruccion)",
    r"\b(show|reveal|print|repeat)\b.*\b(system\s+prompt|your\s+instructions)\b",
    r"\bactua\s+como\b.*\b(otro|diferente)\b",
    r"\ba\s+partir\s+de\s+ahora\s+(afirma|di|responde)\b",
)

_COMPILED_REFUSALS = {
    topic: tuple(re.compile(p) for p in patterns) for topic, patterns in _REFUSAL_PATTERNS.items()
}
_COMPILED_INJECTIONS = tuple(re.compile(p) for p in _INJECTION_PATTERNS)


def _refusal_text_for(topic: str, policy: dict[str, Any]) -> str:
    """Take the wording from the corpus, so the policy has one home."""
    # Both sides are accent-folded: "compensación" must match a corpus entry that
    # normalises to "compensacion", which is exactly the bug this line once had.
    keyword = normalize(topic).split()[0]
    for entry in policy.get("out_of_scope", []):
        if keyword in normalize(entry.get("topic", "")):
            text = entry.get("answer_es", "")
            if text:
                return " ".join(text.split())
    return (
        "No tengo información sobre eso y no es algo que me corresponda comentar. "
        "Puedo hablarte de su perfil, experiencia, habilidades y proyectos."
    )


def evaluate(question: str, policy: dict[str, Any]) -> PolicyDecision:
    text = normalize(question)

    injection = any(pattern.search(text) for pattern in _COMPILED_INJECTIONS)

    for topic, patterns in _COMPILED_REFUSALS.items():
        if any(pattern.search(text) for pattern in patterns):
            return PolicyDecision(
                refuse=True,
                refusal_text=_refusal_text_for(topic, policy),
                topic=topic,
                injection_suspected=injection,
            )

    return PolicyDecision(injection_suspected=injection)
