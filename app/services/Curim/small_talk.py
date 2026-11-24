"""
Saludos, agradecimientos y "¿qué puedes hacer?".

No son preguntas sobre documentos: buscarlas respondía "No encontré
información". Solo se aplica si TODO el mensaje es una frase conocida, para
no interceptar nunca una pregunta real ("hola, ¿cuál es el deducible?").
"""

import re
import unicodedata
from typing import Optional

_GREETING_ES = (
    r"(hola|buenas|buenos dias|buenas tardes|buenas noches|saludos)"
    r"( (hola|buenas|buenos dias|buenas tardes|buenas noches|curim|que tal|como estas))*"
)
_GREETING_EN = (
    r"(hello|hi|hey|good morning|good afternoon|good evening)"
    r"( (there|curim|good morning|good afternoon|good evening|how are you))*"
)

_REPLIES = [
    (
        _GREETING_ES,
        "Hola, soy Curim. ¿Qué necesitas consultar en los documentos?",
    ),
    (
        _GREETING_EN,
        "Hello, I'm Curim. What would you like to look up in the documents?",
    ),
    (
        r"(muchas |mil )?gracias( curim)?|(ok|vale|perfecto|listo) (muchas )?gracias",
        "Con gusto. Si tienes otra consulta, aquí estoy.",
    ),
    (
        r"(thanks|thank you)( so much| very much| a lot)?( curim)?",
        "You're welcome. If you have another question, I'm here.",
    ),
    (
        r"(que puedes hacer|en que (me )?puedes ayudar(me)?|como (me )?puedes ayudar(me)?"
        r"|quien eres|que eres|como funcionas|ayuda)",
        "Soy Curim, el asistente de Curiman Brokers Group. Respondo preguntas sobre los "
        "documentos a los que tienes acceso: coberturas, plazos, requisitos, montos o "
        "procedimientos, e indico de qué documento sale cada respuesta.",
    ),
    (
        r"(what can you do|how can you help( me)?|who are you|what are you|how do you work|help)",
        "I'm Curim, the Curiman Brokers Group assistant. I answer questions about the "
        "documents you have access to: coverage, deadlines, requirements, amounts or "
        "procedures, and I show which document each answer comes from.",
    ),
]
_COMPILED = [(re.compile(pattern), reply) for pattern, reply in _REPLIES]
REPLY_TEXTS = frozenset(reply for _, reply in _REPLIES)


def _normalize(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación."""
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


def small_talk_reply(text: Optional[str]) -> Optional[str]:
    """Respuesta fija si el mensaje es solo cortesía; None si es una pregunta."""
    normalized = _normalize(text or "")
    for pattern, reply in _COMPILED:
        if pattern.fullmatch(normalized):
            return reply
    return None
