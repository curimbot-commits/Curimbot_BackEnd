"""
Módulo de configuración centralizado de la aplicación.

Gestiona JWT, base de datos, CORS, Curim (búsqueda semántica/RAG) y síntesis de voz.
Carga variables de entorno desde .env mediante pydantic-settings.
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración centralizada de la aplicación con validación de Pydantic.
    Las variables de entorno sobrescriben estos valores por defecto.
    """
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    # ── Email ──────────────────────────────────────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    FROM_EMAIL: Optional[str] = None

    # ── Autenticación ──────────────────────────────────────────────────────────
    SECRET_KEY: str = "defaultsecret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Base de datos ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./asistente_docs.db"

    # ── CORS ───────────────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["http://localhost:4200"]

    # ── Curim / Gemini ─────────────────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    Curim_STORAGE_PATH: str = "./storage/Curim_data"
    Curim_CACHE_ENABLED: bool = True
    Curim_CACHE_TTL_DAYS: int = 7

    # ── RAG ────────────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    TOP_K_RESULTS: int = 3

    # ── Text-to-Speech ─────────────────────────────────────────────────────────
    DEFAULT_VOICE: str = "es-PA-MargaritaNeural"
    VOICE_SPEED: str = "+20%"

    # ── Validación ─────────────────────────────────────────────────────────────

    def validate_Curim(self):
        """
        Valida que Curim esté configurado correctamente.
        """
        if not self.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY no configurado. "
                "Por favor, agrega tu API key de Gemini en el archivo .env"
            )

        os.makedirs(os.path.join(self.Curim_STORAGE_PATH, "chroma_db"), exist_ok=True)
        os.makedirs(os.path.join(self.Curim_STORAGE_PATH, "cache"), exist_ok=True)


# Instancia global — importar con: from app.core.config import settings
settings = Settings()

# Mantener soporte a imports antiguos por retrocompatibilidad momentánea si hiciera falta (pero lo ideal es usar `settings.VARIABLE`)
RESEND_API_KEY = settings.RESEND_API_KEY
FROM_EMAIL = settings.FROM_EMAIL
