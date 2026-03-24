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

    # ── Entorno ──────────────────────────────────────────────────────────────────
    DEBUG: bool = True  # Cambiar a False en producción

    # ── Email ──────────────────────────────────────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    FROM_EMAIL: Optional[str] = None

    # ── Autenticación (Tiempos de expiración) ──────────────────────────────────
    SECRET_KEY: str = "defaultsecret"
    ALGORITHM: str = "HS256"
    
    # Tiempo de vida del token de acceso (recomendado 15-30 min)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Tiempo máximo de la sesión completa (Refresh Token)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # Tiempo de inactividad permitido antes de cerrar sesión (minutos)
    SESSION_INACTIVITY_TIMEOUT_MINUTES: int = 60
    
    # Tiempo máximo de vida absoluta de una sesión (días)
    MAX_SESSION_LIFETIME_DAYS: int = 30

    # ── Base de datos ──────────────────────────────────────────────────────────
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: str = "3306"
    DB_NAME: str = "curim_db"
    DATABASE_URL: Optional[str] = None
    
    @property
    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

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
