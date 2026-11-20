"""El asistente responde en el idioma de la pregunta (es/en)."""

from app.services.Curim.language import detect_language, message


def test_detect_language():
    assert detect_language("How many vacation days do I get?") == "en"
    assert detect_language("what are your rules?") == "en"
    assert detect_language("¿Cuántos días de vacaciones tengo?") == "es"
    assert detect_language("que dice el reglamento sobre el teletrabajo") == "es"
    assert detect_language("") is None


def test_fixed_messages_follow_question_language():
    assert message("no_context", "en").startswith("I couldn't find")
    assert message("no_context", "es").startswith("No encontr")
    assert message("no_context", None).startswith("No encontr")


def test_semantic_cache_does_not_cross_languages(tmp_path):
    import numpy as np

    from app.services.Curim.semantic_cache import SemanticCache

    class SameVector:
        """Embeddings idénticos: simula preguntas equivalentes en dos idiomas."""
        def encode(self, text):
            return np.array([1.0, 0.0])

    cache = SemanticCache(similarity_threshold=0.85, embedding_model=SameVector())
    cache.cache_file = str(tmp_path / "semantic_cache.json")
    cache.cache = {}
    cache.set(1, "¿Cuántos días de vacaciones tengo?", "Tienes 15 días.", 0.9, [1])

    assert cache.get(1, "How many vacation days do I get?") is None
    assert cache.get(1, "¿Cuántos días de vacaciones hay?")["answer"] == "Tienes 15 días."
