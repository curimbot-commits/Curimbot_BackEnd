"""
Detección ligera del idioma de una pregunta (español / inglés).

Se usa para:
  - indicar al modelo en qué idioma responder (los documentos y las
    instrucciones están en español y arrastraban la respuesta al español),
  - traducir los mensajes fijos (p. ej. "no encontré información"),
  - que la caché semántica no devuelva una respuesta en otro idioma: el
    modelo de embeddings es multilingüe, así que "how many vacation days"
    y "cuántos días de vacaciones" se parecen mucho.

Heurística por palabras frecuentes: suficiente para es/en y sin
dependencias nuevas. Devuelve None si no está claro.
"""

import re
from typing import Optional

_ES_CHARS = re.compile(r"[ñ¿¡áéíóú]", re.IGNORECASE)
_WORD = re.compile(r"[a-záéíóúñü']+", re.IGNORECASE)

_ES_WORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "que", "qué", "y", "en",
    "es", "son", "por", "para", "con", "como", "cómo", "cuál", "cual", "cuáles",
    "cuales", "cuánto", "cuanto", "cuántos", "cuantos", "cuándo", "cuando",
    "dónde", "donde", "quién", "quien", "se", "su", "sus", "lo", "al", "hay",
    "puedo", "tengo", "tiene", "dice", "sobre", "mi", "mis", "me", "tus", "tu",
    "este", "esta", "esto", "pero", "más", "mas", "días", "dias", "qué",
}
_EN_WORDS = {
    "the", "a", "an", "of", "and", "in", "is", "are", "for", "with", "how",
    "what", "which", "when", "where", "who", "why", "do", "does", "can", "i",
    "my", "your", "you", "to", "it", "this", "that", "there", "about", "on",
    "many", "much", "get", "have", "has", "tell", "me", "please", "should",
    "be", "was", "were", "will", "would", "any", "days", "rules",
}

LANGUAGE_NAMES = {"es": "español", "en": "inglés (English)"}

MESSAGES = {
    "no_context": {
        "es": "No encontré información sobre eso en los documentos disponibles.",
        "en": "I couldn't find information about that in the available documents.",
    },
    "no_answer": {
        "es": "No pude generar una respuesta.",
        "en": "I couldn't generate an answer.",
    },
}


def detect_language(text: Optional[str]) -> Optional[str]:
    """'es', 'en' o None si no se puede decidir."""
    if not text:
        return None
    words = [w.lower() for w in _WORD.findall(text)]
    es = sum(w in _ES_WORDS for w in words) + 2 * len(_ES_CHARS.findall(text))
    en = sum(w in _EN_WORDS for w in words)
    if es == en:
        return None
    return "es" if es > en else "en"


def message(key: str, lang: Optional[str]) -> str:
    """Mensaje fijo en el idioma de la pregunta (español si no se sabe)."""
    texts = MESSAGES[key]
    return texts.get(lang or "es", texts["es"])
