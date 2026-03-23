"""
Módulo de configuración de base de datos MySQL.

Gestiona la conexión MySQL con SQLAlchemy: motor, sesiones, base declarativa
y la dependencia `get_db` para inyección en endpoints FastAPI.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# CONFIGURACIÓN DE CONEXIÓN MYSQL
# =========================================================

from app.core.config import settings
DATABASE_URL = settings.get_database_url


# =========================================================
# MOTOR SQLALCHEMY
# =========================================================

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={
        "charset": "utf8mb4",
        "use_unicode": True,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    },
    echo=False,
)


# =========================================================
# SESIONES Y BASE DECLARATIVA
# =========================================================

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# =========================================================
# DEPENDENCY INJECTION PARA FASTAPI
# =========================================================

def get_db():
    """
    Proporciona una sesión de base de datos MySQL por request.

    Crea una sesión nueva, la entrega al endpoint vía yield y la cierra
    en el bloque finally (la conexión regresa al pool automáticamente).

    Yields:
        Session: Sesión SQLAlchemy lista para usar en el endpoint.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# INICIALIZACIÓN DE BASE DE DATOS
# =========================================================

def init_db():
    """
    Crea todas las tablas definidas en los modelos.

    IMPORTANTE: En producción usar Alembic para migraciones.
    Esta función no elimina datos existentes.
    """
    from app.models import models
    Base.metadata.create_all(bind=engine)