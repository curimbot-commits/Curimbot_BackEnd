"""
Script de inicialización de base de datos.

Este módulo proporciona funciones para crear la estructura de base de datos
e inicializar datos básicos (roles, usuarios iniciales, etc.) necesarios
para que la aplicación funcione correctamente.

Funcionalidad:
    - Crear todas las tablas de base de datos
    - Inicializar roles básicos (admin, user)
    - Seed de datos iniciales
    - Validación de estructura

Uso:
    python init_db.py
    
    O desde código:
    from app.core.database_init import init_roles, main
    main()

Notas de seguridad:
    - Ejecutar solo en entornos de desarrollo o durante deployment
    - Verificar que las variables de entorno están correctamente configuradas
    - En producción, usar migrations con Alembic
"""

from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.models import Role
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_roles(db: Session):
    """
    Inicializar roles básicos en la base de datos.
    
    Crea los roles fundamentales (admin, user) que se usan en todo el sistema
    para control de acceso. Se ejecuta idempotentemente: si ya existen, no los
    recrea.
    
    Roles creados:
        - **admin**: Acceso total al sistema
            - Puede ver/editar cualquier recurso
            - Acceso a endpoints administrativos
            - Gestión de usuarios
            - Configuración del sistema
        
        - **user**: Acceso estándar
            - Puede ver/editar solo sus propios recursos
            - Acceso a funcionalidades básicas
            - No puede administrar sistema
            - No puede ver datos de otros usuarios
    
    Operación:
        1. Define lista de roles a crear
        2. Verifica si cada rol ya existe
        3. Si no existe, crea nuevo Role
        4. Realiza commit de la transacción
        5. Registra operación en logs
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
    
    Raises:
        Exception: Si hay error en la BD durante commit
    
    Example:
        from app.db.database import SessionLocal
        from app.core.database_init import init_roles
        
        db = SessionLocal()
        try:
            init_roles(db)
            print("Roles initialized successfully")
        finally:
            db.close()
    
    Idempotencia:
        - Seguro llamar múltiples veces
        - No crea duplicados
        - Verifica existencia antes de crear
    
    Logging:
        - INFO: Cuando se crea rol
        - INFO: Si rol ya existe
        - ERROR: Si hay error durante commit
    
    Roles en la aplicación:
        Los roles se usan en:
        - Decoradores `@require_admin` en endpoints
        - Filtrado de datos por usuario
        - Control de funcionalidades
        - Auditoría de acciones
    
    Estructura de datos:
        ```
        Role (tabla):
        - id: PK (auto-incremento)
        - name: Nombre único (admin, user, etc.)
        - description: Descripción legible
        - created_at: Timestamp de creación
        ```
    """
    # Definir roles a inicializar
    roles_data = [
        {
            "name": "admin",
            "description": "Administrator with full system access"
        },
        {
            "name": "user",
            "description": "Regular user with standard permissions"
        }
    ]
    
    # Iterar sobre cada rol a crear
    for role_data in roles_data:
        # Verificar si el rol ya existe en la BD
        existing_role = db.query(Role).filter(Role.name == role_data["name"]).first()
        
        if not existing_role:
            # Si no existe, crear nuevo rol
            new_role = Role(**role_data)
            db.add(new_role)
            logger.info(f"Created role: {role_data['name']}")
        else:
            # Si ya existe, no hacer nada (idempotente)
            logger.info(f"Role already exists: {role_data['name']}")
    
    # Guardar cambios en la BD
    try:
        db.commit()
        logger.info("Roles initialized successfully")
    except Exception as e:
        # En caso de error, deshacer cambios
        db.rollback()
        logger.error(f"Error initializing roles: {e}")
        raise


def main():
    """
    Función principal para ejecutar la inicialización completa de la BD.
    
    Realiza todas las operaciones necesarias para preparar la base de datos:
    1. Crea todas las tablas (si no existen)
    2. Inicializa datos básicos (roles)
    3. Maneja errores apropiadamente
    
    Flujo de ejecución:
        1. Crear estructura de tablas con SQLAlchemy ORM
        2. Abrir sesión de BD
        3. Inicializar roles básicos
        4. Cerrar sesión correctamente
    
    Operaciones:
        - **upgrade_to_head()**: Aplica migraciones de Alembic pendientes
            - Lee definiciones de modelos
            - Crea tablas en BD
            - Crea índices y constrains
            - Idempotente (seguro llamar múltiples veces)
        
        - **init_roles()**: Inicializa roles básicos
    
    Uso desde línea de comandos:
        ```
        python init_db.py
        ```
    
    Uso desde código:
        ```
        from app.core.database_init import main
        main()
        ```
    
    Uso en startup de FastAPI:
        ```
        from fastapi import FastAPI
        from app.core.database_init import main
        
        app = FastAPI()
        
        @app.on_event("startup")
        async def startup():
            main()
            logger.info("Database initialized")
        ```
    
    Variables de entorno requeridas:
        - DATABASE_URL: URL de conexión a la BD
        - (definidas en .env)
    
    Excepciones:
        - Si DATABASE_URL no está configurado
        - Si no hay permisos de conexión a BD
        - Si hay errores en la estructura de modelos
    
    Logs generados:
        - INFO: "Roles initialized successfully"
        - ERROR: Si hay problemas (muestra detalles)
    
    Ejemplo de output:
        ```
        INFO:root:Created role: admin
        INFO:root:Role already exists: user
        INFO:root:Roles initialized successfully
        ```
    
    Best practices:
        - Ejecutar en deployment inicial
        - Ejecutar solo una vez (idempotente)
        - Usar antes de ejecutar aplicación
        - Monitorear logs para verificar
    
    Notas de seguridad:
        - No crea usuarios por defecto
        - No asigna permisos automáticamente
        - Requiere login para crear usuarios
        - Admininstrador debe crearse manualmente primero
    
    Consideraciones de producción:
        - Versionar cambios de schema
        - Hacer backup de BD antes de cambios
        - Usar transacciones si hay múltiples inicializaciones
    """
    # Aplicar migraciones de Alembic (única fuente del esquema)
    from app.db.migrations import upgrade_to_head
    upgrade_to_head()
    
    # Abrir sesión de base de datos
    db = SessionLocal()
    try:
        # Inicializar datos básicos (roles)
        init_roles(db)
    finally:
        # Cerrar sesión siempre, incluso si hay error
        db.close()


if __name__ == "__main__":
    """
    Entry point para ejecutar como script.
    
    Permite ejecutar el script directamente desde línea de comandos:
        python init_db.py
    
    Alternativas para ejecutar:
    
    1. Desde FastAPI startup:
        ```
        @app.on_event("startup")
        async def startup():
            from app.core.database_init import main
            main()
        ```
    
    2. Desde command line:
        ```
        python -m app.core.database_init
        ```
    
    3. Como parte de deployment:
        ```
        python init_db.py && uvicorn app.main:app
        ```
    """
    main()
