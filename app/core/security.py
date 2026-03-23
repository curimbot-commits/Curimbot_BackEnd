# app/core/security.py
"""
Este archivo de utilidades ha sido refactorizado. 
Todos los esquemas de Pydantic ahora residen en app/schemas/auth_schemas.py.
"""

from app.services.security_service import verify_password, hash_password as get_password_hash

__all__ = ["verify_password", "get_password_hash"]
