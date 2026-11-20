import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import logging

load_dotenv()  # ENC_KEY / ENC_KEY_PATH / ENV pueden venir de .env

logger = logging.getLogger(__name__)
KEY_PATH = os.getenv("ENC_KEY_PATH", "./enc.key")


def _load_or_create_key():
    """
    Obtiene la clave Fernet para cifrar documentos.

    Orden de prioridad:
      1. Variable de entorno ENC_KEY (recomendado en producción: secreto del
         proveedor de despliegue, nunca dentro del repositorio ni de la imagen).
      2. Archivo en ENC_KEY_PATH (desarrollo local).
      3. Solo fuera de producción: generar una clave nueva en ENC_KEY_PATH.

    En producción (ENV=production) no se genera una clave automáticamente:
    una clave efímera dejaría los documentos indescifrables tras cada redeploy.
    """
    env_key = os.getenv("ENC_KEY")
    if env_key:
        return env_key.strip().encode()

    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read().strip()

    if os.getenv("ENV", "development").lower() == "production":
        raise RuntimeError(
            "ENC_KEY no configurada en producción. Define la variable de entorno "
            "ENC_KEY con una clave Fernet persistente."
        )

    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    logger.warning(f"Clave de cifrado nueva generada en {KEY_PATH} (solo desarrollo)")
    return key

_FERNET = Fernet(_load_or_create_key())

def encrypt_bytes(data: bytes) -> bytes:
    return _FERNET.encrypt(data)

def decrypt_bytes(token: bytes) -> bytes:
    return _FERNET.decrypt(token)
