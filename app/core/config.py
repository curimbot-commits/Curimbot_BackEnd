"""
Módulo de configuración centralizado de la aplicación.

Gestiona JWT, base de datos, CORS, Curim (búsqueda semántica/RAG) y síntesis de voz.
Carga variables de entorno desde .env mediante pydantic-settings.
"""

from pydantic import field_validator
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

    # ── Entorno ──────────────────────────────────────────────────────────────
    ENV: str = "development"
    DEBUG: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() == "production"

    # ── Email ────────────────────────────────────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    FROM_EMAIL: Optional[str] = None

    # ── Autenticación ────────────────────────────────────────────────────────
    SECRET_KEY: str = "defaultsecret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    SESSION_INACTIVITY_TIMEOUT_MINUTES: int = 60
    MAX_SESSION_LIFETIME_DAYS: int = 30

    # ── Base de datos ────────────────────────────────────────────────────────
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: str = "3306"
    DB_NAME: str = "curim_db"
    DATABASE_URL: Optional[str] = None

    # ── Cookies de autenticación ─────────────────────────────────────────────
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None

    @field_validator("COOKIE_DOMAIN", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @property
    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    # ── CORS ────────────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["http://localhost:4200"]

    # ── Curim / Gemini ──────────────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    # Modelos (cambiables por entorno sin desplegar código). Las keys nuevas
    # no pueden usar gemini-2.5-flash ("no longer available to new users").
    GEMINI_TEXT_MODEL: str = "gemini-3.5-flash"
    # Se prueban en orden si el principal falla por saturación (429/5xx),
    # timeout o modelo no disponible (404).
    GEMINI_TEXT_FALLBACK_MODELS: str = "gemini-3.8-flash,gemini-3.5-flash-lite"
    GEMINI_TEXT_TIMEOUT_SECONDS: int = 30
    GEMINI_LIVE_MODEL: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    Curim_STORAGE_PATH: str = "./storage/Curim_data"
    Curim_CACHE_ENABLED: bool = True
    Curim_CACHE_TTL_DAYS: int = 7

    # ── RAG ──────────────────────────────────────────────────────────────────
    # chunk_size y chunk_overlap deben estar en caracteres.
    # MiniLM-L12 multilingüe tiene ventana de 512 tokens (~380 palabras,
    # ~1800-2200 caracteres en español). 1000/200 es un buen punto medio
    # para documentos financieros y de seguros.
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K_RESULTS: int = 6

    # Umbral de distancia coseno para descartar chunks irrelevantes.
    # Menor = más relevante. Calibrar en Fase 2 con datos reales.
    RAG_MAX_DISTANCE: float = 0.7

    # ── Text-to-Speech ──────────────────────────────────────────────────────
    DEFAULT_VOICE: str = "es-PA-MargaritaNeural"
    VOICE_SPEED: str = "+20%"

    # ── Validación ──────────────────────────────────────────────────────────
    def validate_production(self) -> None:
        """
        Impide arrancar en producción con una configuración insegura.
        No hace nada si ENV != production.
        """
        if not self.is_production:
            return
        problems = []
        if self.SECRET_KEY == "defaultsecret" or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY debe definirse y tener al menos 32 caracteres")
        if not self.COOKIE_SECURE:
            problems.append("COOKIE_SECURE debe ser True (HTTPS)")
        if self.DEBUG:
            problems.append("DEBUG debe ser False")
        if problems:
            raise ValueError("Configuración de producción insegura: " + "; ".join(problems))

    def validate_Curim(self):
        if not self.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY no configurado. "
                "Por favor, agrega tu API key de Gemini en el archivo .env"
            )
        os.makedirs(os.path.join(self.Curim_STORAGE_PATH, "chroma_db"), exist_ok=True)
        os.makedirs(os.path.join(self.Curim_STORAGE_PATH, "cache"), exist_ok=True)


settings = Settings()

RESEND_API_KEY = settings.RESEND_API_KEY
FROM_EMAIL = settings.FROM_EMAIL