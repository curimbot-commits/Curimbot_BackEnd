# app/services/security_service.py
import os
import hashlib
import hmac
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
import bcrypt
from fastapi import HTTPException, status
import logging
import uuid

logger = logging.getLogger(__name__)

from app.core.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
inactivity_timeout = settings.SESSION_INACTIVITY_TIMEOUT_MINUTES

# ========================================
# CONFIGURACIÓN DE BCRYPT
# ========================================
BCRYPT_ROUNDS = 12  # equivalente al default de passlib
# passlib usa SHA-256 antes de bcrypt para soportar passwords largos
BCRYPT_SHA256_SALT = b"bcrypt_sha256"  # constante que usa passlib internamente
BCRYPT_SHA256_IDENT = "$bcrypt-sha256$"


def _prehash_password(password: str) -> bytes:
    """
    Pre-hashear contraseña con SHA-256, replicando lo que hace
    passlib.bcrypt_sha256 antes de aplicar bcrypt.

    Esto permite:
    - Soportar contraseñas de cualquier longitud (>72 bytes)
    - Mantener compatibilidad con hashes existentes de passlib
    """
    if isinstance(password, str):
        password = password.encode("utf-8")
    return hashlib.sha256(password).digest()


def hash_password(password: str) -> str:
    """
    Genera un hash bcrypt-sha256 compatible con el formato de passlib.

    Formato producido: $bcrypt-sha256$v=2,t=2b,r=12$<salt>$<hash>
    Esto es compatible con hashes generados por passlib.bcrypt_sha256.
    """
    # 1. Pre-hash con SHA-256 (passlib lo hace para soportar passwords largos)
    prehashed = _prehash_password(password)

    # 2. Aplicar bcrypt
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    bcrypt_hash = bcrypt.hashpw(prehashed, salt).decode("utf-8")

    # bcrypt_hash viene como: $2b$12$<22-char-salt><31-char-hash>
    # Extraer salt y hash
    parts = bcrypt_hash.split("$")
    # parts = ['', '2b', '12', '<salt+hash>']
    version = parts[1]              # "2b"
    rounds = parts[2]               # "12"
    salt_and_hash = parts[3]        # <salt><hash>
    salt_b64 = salt_and_hash[:22]   # salt en base64 (22 chars)
    hash_b64 = salt_and_hash[22:]   # hash en base64 (31 chars)

    # 3. Formatear como passlib bcrypt_sha256
    #    Formato: $bcrypt-sha256$v=2,t=2b,r=12$<salt>$<hash>
    return f"$bcrypt-sha256$v=2,t={version},r={rounds}${salt_b64}${hash_b64}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica contraseña contra hash bcrypt-sha256.

    Soporta:
    - Formato nuevo: $bcrypt-sha256$v=2,t=2b,r=12$<salt>$<hash>
    - Formato bcrypt estándar: $2b$12$<salt+hash> (por si acaso)
    """
    try:
        if not hashed_password:
            return False

        # --- Caso 1: Formato passlib bcrypt_sha256 ---
        if hashed_password.startswith(BCRYPT_SHA256_IDENT):
            prehashed = _prehash_password(plain_password)

            # Parsear el hash de passlib
            # $bcrypt-sha256$v=2,t=2b,r=12$<salt>$<hash>
            parts = hashed_password.split("$")
            # parts = ['', 'bcrypt-sha256', 'v=2,t=2b,r=12', '<salt>', '<hash>']
            if len(parts) != 5:
                logger.error(f"Formato bcrypt-sha256 inválido: {hashed_password[:30]}...")
                return False

            params = parts[2]  # "v=2,t=2b,r=12"
            salt_b64 = parts[3]
            hash_b64 = parts[4]

            # Reconstruir el hash bcrypt estándar que bcrypt.checkpw entiende
            # Formato: $2b$12$<salt_b64><hash_b64>
            version = "2b"
            rounds = "12"
            for param in params.split(","):
                if param.startswith("t="):
                    version = param[2:]
                elif param.startswith("r="):
                    rounds = param[2:]

            bcrypt_hash = f"${version}${rounds}${salt_b64}{hash_b64}"

            return bcrypt.checkpw(prehashed, bcrypt_hash.encode("utf-8"))

        # --- Caso 2: Formato bcrypt estándar (por si acaso) ---
        elif hashed_password.startswith("$2"):
            prehashed = _prehash_password(plain_password)
            return bcrypt.checkpw(prehashed, hashed_password.encode("utf-8"))

        else:
            logger.error(f"Formato de hash desconocido: {hashed_password[:30]}...")
            return False

    except (ValueError, TypeError, AttributeError) as e:
        logger.error(f"Error verificando password: {e}")
        logger.error(f"Hash format: {hashed_password[:30] if hashed_password else 'None'}...")
        return False

# ========================================
#  FUNCIONES DE JWT
# ========================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un JWT access token.
    
    Args:
        data: Datos a incluir en el token (user_id, role, email)
        expires_delta: Tiempo de expiración personalizado (opcional)
        
    Returns:
        str: Token JWT codificado
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Crea un JWT refresh token.
    
    Args:
        data: Datos a incluir en el token (user_id, role)
        
    Returns:
        str: Token JWT codificado
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


TWO_FACTOR_CHALLENGE_MINUTES = 5


def create_2fa_challenge_token(user_id: int) -> str:
    """
    Crea el token del paso intermedio del login con 2FA.

    Prueba que la contraseña ya se verificó, sin que el cliente tenga que
    guardarla. Dura 5 minutos, es de un solo uso (su `jti` se revoca al
    usarse) y su tipo `2fa_challenge` impide usarlo como access token.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=TWO_FACTOR_CHALLENGE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "2fa_challenge",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un JWT token.
    
    Args:
        token: Token JWT a decodificar
        
    Returns:
        dict: Payload del token
        
    Raises:
        HTTPException: Si el token es inválido o expirado
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"Token decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )