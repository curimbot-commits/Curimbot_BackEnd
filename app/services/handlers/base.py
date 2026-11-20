"""
Módulo base de handlers para patrones Chain of Responsibility.

Implementa clases base para múltiples cadenas de handlers utilizadas
en diferentes flujos de la aplicación:
    - DocumentHandler: Procesamiento de documentos (upload)
    - SignupHandler: Registro de usuarios
    - RefreshTokenHandler: Refresco de tokens
    - RoleChangeHandler: Cambio de roles
    - ChangePasswordHandler: Cambio de contraseña

Patrón Chain of Responsibility:
    - Cada handler procesa una parte de la lógica
    - Pasa contexto al siguiente handler
    - Cada handler es independiente y reutilizable
    - Fácil agregar/remover handlers sin cambiar código existente

Utilidad:
    - Modularizar flujos complejos
    - Separar responsabilidades
    - Detectar ciclos infinitos
    - Rastrear ejecuciones por correlación
"""

from abc import ABC, abstractmethod
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# =========================================================
# UTILIDADES
# =========================================================

def verify_chain_integrity(handler_chain):
    """
    Verificar que la cadena de handlers esté bien formada sin ciclos.
    
    Recorre la cadena desde el handler inicial hasta el final,
    verificando que no haya referencias circulares.
    
    Algoritmo:
        1. Usar set para rastrear IDs de handlers visitados
        2. Iterar desde handler inicial
        3. Si ID ya visitado, hay ciclo
        4. Agregar a visited y avanzar
        5. Si llegamos a None sin ciclos, cadena es válida
    
    Args:
        handler_chain: Handler inicial de la cadena
    
    Returns:
        bool: True si válida, False si hay ciclos
    
    Example:
        validate_handler = ValidateHandler()
        extract_handler = ExtractHandler()
        save_handler = SaveHandler()
        
        validate_handler.set_next(extract_handler)
        extract_handler.set_next(save_handler)
        
        if verify_chain_integrity(validate_handler):
            print("Cadena válida")
        else:
            print("Ciclo detectado en cadena")
    
    Detección de ciclos:
        - Almacena ID de objeto (memory address)
        - Si ID se repite, hay ciclo
        - Reporta handler que causa ciclo
    
    Performance:
        - O(n) donde n = handlers en cadena
        - Típicamente < 1ms para cadenas normales
    
    Notas:
        - Se debe llamar una vez al inicializar cadena
        - Usar en startup o test suite
        - No en ruta crítica de requests
    """
    visited = set()
    current = handler_chain
    chain_list = []
    
    while current is not None:
        handler_name = current.__class__.__name__
        handler_id = id(current)
        
        # Detectar ciclos
        if handler_id in visited:
            logger.error(
                f"Ciclo detectado en cadena de handlers. "
                f"Cadena hasta ciclo: {' -> '.join(chain_list)}. "
                f"Handler que repite: {handler_name}"
            )
            return False
        
        visited.add(handler_id)
        chain_list.append(f"{handler_name}(id={handler_id})")
        
        # Avanzar al siguiente
        current = current._next_handler
    
    # Cadena válida sin ciclos
    logger.debug(f"Cadena de handlers válida: {' -> '.join(chain_list)}")
    return True


# =========================================================
# DOCUMENT HANDLERS
# =========================================================

class DocumentContext:
    """
    Contexto para procesamiento de documentos.
    
    Encapsula toda la información necesaria durante el pipeline
    de procesamiento de un documento desde upload hasta indexación.
    
    Flujo de vida:
        1. Creado con filename, content, user, db
        2. Pasa por cadena de handlers
        3. Cada handler agrega/modifica campos
        4. Al final, document está listo para BD
    
    Campos iniciales (entrada):
        - filename: Nombre del archivo original
        - content: Bytes del archivo
        - user: Usuario que subió el archivo
        - db: Sesión de BD
        - mimetype: Tipo MIME opcional
    
    Campos de salida (llenados por handlers):
        - document: Modelo Document creado
        - text: Texto extraído del contenido
        - file_type: Tipo de archivo (enum)
        - encrypted_content: Bytes encriptados (si aplica)
        - extension: Extensión del archivo
        - size: Tamaño en bytes
    
    Campos Curim:
        - Curim_indexed: Si fue indexado en Curim
        - Curim_chunks: Cantidad de chunks
        - Curim_error: Mensaje de error si aplica
    
    Campos de rastreo:
        - correlation_id: ID para tracing de requests
        - handler_execution_count: Contador para detectar ciclos
    
    Validaciones en __init__:
        - filename no vacío y es string
        - content es bytes
        - user tiene atributo id
        - db es sesión válida
    
    Example:
        context = DocumentContext(
            filename="reporte.pdf",
            content=file_bytes,
            user=current_user,
            db=db_session,
            mimetype="application/pdf"
        )
        
        # Pasar por handlers
        validate_handler.handle(context)
        
        # Acceder resultado
        print(f"Documento ID: {context.document.id}")
        print(f"Texto extraído: {context.text[:100]}")
    
    Estructura después de procesamiento:
        context.document: Document model (guardado en BD)
        context.text: Texto completo extraído
        context.file_type: FileType enum
        context.encrypted_content: Bytes encriptados
        context.Curim_indexed: True/False
        context.Curim_chunks: 250
    """
    
    def __init__(
        self,
        filename: str,
        content: bytes,
        user,
        db,
        mimetype: str = None
    ):
        if not filename or not isinstance(filename, str):
            raise ValueError("filename inválido en DocumentContext")
        if not isinstance(content, bytes):
            raise ValueError("content debe ser bytes en DocumentContext")
        if not user or not hasattr(user, 'id'):
            raise ValueError("user inválido en DocumentContext")
        if not db:
            raise ValueError("db inválido en DocumentContext")

        # Entrada
        self.filename = filename
        self.content = content
        self.user = user
        self.db = db
        self.mimetype = mimetype

        # Procesamiento
        self.document = None
        self.text = None
        self.file_type = None
        self.encrypted_content = None
        self.extension = None
        self.size = len(content) if content else 0

        # Opcionales (antes asignados dinámicamente)
        self.file = None
        self.nlp_data = None
        self.correlation_id = None
        self.handler_execution_count = {}

        # Curim
        self.Curim_indexed = False
        self.Curim_chunks = 0
        self.Curim_error = None


class DocumentHandler(ABC):
    """
    Clase base para handlers de documentos (Chain of Responsibility).
    
    Implementa el patrón para procesar documentos a través de una cadena
    de handlers especializados. Cada handler realiza una tarea específica
    (validar, extraer, encriptar, guardar, indexar, loguear).
    
    Cadena típica:
        ValidateFileHandler
            ↓
        ExtractTextHandler
            ↓
        [EncryptFileHandler] (opcional)
            ↓
        SaveToDBHandler
            ↓
        IndexCurimHandler
            ↓
        LogActivityHandler
    
    Características:
        - Detección de ciclos infinitos
        - Rastreo con correlation_id
        - Contador de ejecuciones por handler
        - Logging de cada etapa
        - Manejo de excepciones por etapa
    
    Uso:
        class CustomHandler(DocumentHandler):
            async def _handle(self, context):
                # Tu lógica aquí
                context.my_field = "valor"
        
        handler1 = CustomHandler()
        handler2 = AnotherHandler()
        handler1.set_next(handler2)
        
        await handler1.handle(context)
    
    Performance:
        - Cada handler típicamente 50-500ms
        - Overhead de cadena < 1ms
    """
    
    _execution_count = {}
    
    def __init__(self):
        """Inicializar handler."""
        self._next_handler = None
    
    def set_next(self, handler: "DocumentHandler") -> "DocumentHandler":
        """
        Establecer siguiente handler en la cadena.
        
        Args:
            handler: Handler siguiente
        
        Returns:
            DocumentHandler: El handler para encadenamiento
        
        Raises:
            ValueError: Si handler intenta ser su propio siguiente
        
        Example:
            validate.set_next(extract).set_next(save)
        """
        if handler is self:
            raise ValueError(
                f"Un handler no puede ser su propio siguiente: {self.__class__.__name__}"
            )
        self._next_handler = handler
        return handler
    
    async def handle(self, context: DocumentContext):
        """
        Ejecutar handler actual y continuar cadena.
        
        Operación:
            1. Obtener nombre del handler y correlation_id
            2. Inicializar contador de ejecuciones en contexto
            3. Incrementar contador
            4. Detectar ciclos (si > 2 ejecuciones)
            5. Ejecutar _handle() implementado por subclass
            6. Si hay error, loguear excepción
            7. Si hay siguiente, llamar handle() del siguiente
            8. Si es final, marcar completado
        
        Args:
            context (DocumentContext): Contexto a procesar
        
        Raises:
            RuntimeError: Si se detecta ciclo infinito
            Exception: Cualquier excepción de _handle propagada
        """
        handler_name = self.__class__.__name__
        correlation_id = getattr(context, 'correlation_id', 'unknown')
        key = f"{correlation_id}:{handler_name}"
        
        # Inicializar contador en contexto si no existe
        if key not in context.handler_execution_count:
            context.handler_execution_count[key] = 0
        
        context.handler_execution_count[key] += 1
        
        # Detectar ciclos (handler ejecutado > 2 veces)
        if context.handler_execution_count[key] > 2:
            logger.error(
                f"Ciclo detectado: {handler_name} ejecutado "
                f"{context.handler_execution_count[key]} veces. "
                f"Siguiente: {self._next_handler.__class__.__name__ if self._next_handler else 'None'}"
            )
            raise RuntimeError(f"Ciclo infinito detectado en {handler_name}")
        
        # Ejecutar handler actual
        try:
            logger.debug(
                f"Ejecutando handler {handler_name} (intento {context.handler_execution_count[key]}) "
                f"para archivo: {context.filename}"
            )
            await self._handle(context)
        except Exception as e:
            logger.exception(
                f"Error en handler {handler_name} para archivo {context.filename}: {e}"
            )
            raise
        
        # Continuar cadena
        if self._next_handler:
            logger.debug(f"Continuando: {handler_name} -> {self._next_handler.__class__.__name__}")
            await self._next_handler.handle(context)
        else:
            logger.debug(f"Handler final {handler_name} completó cadena")
    
    @abstractmethod
    async def _handle(self, context: DocumentContext):
        """
        Lógica específica de este handler (implementar en subclass).
        
        Args:
            context (DocumentContext): Contexto a modificar
        """
        pass


# =========================================================
# SIGNUP HANDLERS
# =========================================================

class SignupContext:
    """
    Contexto para proceso de registro de usuarios.
    
    Encapsula datos del usuario durante registro y tokens generados.
    
    Flujo:
        1. Usuario envía email/contraseña
        2. Crea SignupContext con user_data y db
        3. Pasa por handlers (validar, crear usuario, generar tokens)
        4. Al final tiene access_token y refresh_token
    
    Campos:
        - user_data: Datos del usuario (email, password, etc)
        - db: Sesión de BD
        - access_token: Token de acceso (generado)
        - refresh_token: Token de refresco (generado)
    
    Example:
        context = SignupContext(
            user_data={
                "email": "user@example.com",
                "password": "securepass123",
                "name": "John Doe"
            },
            db=db_session
        )
        
        handler_chain.handle(context)
        
        print(f"Access token: {context.access_token}")
    """
    
    def __init__(self, user_data, db):
        """Inicializar contexto de signup."""
        self.user_data = user_data
        self.db = db
        self.access_token = None
        self.refresh_token = None


class SignupHandler(ABC):
    """
    Clase base para handlers de registro de usuarios.
    
    Cadena típica:
        ValidateSignupData
            ↓
        CreateUserHandler
            ↓
        GenerateTokensHandler
            ↓
        SendWelcomeEmailHandler
    
    Example:
        class ValidateSignupHandler(SignupHandler):
            def _handle(self, context):
                email = context.user_data.get('email')
                if not email or '@' not in email:
                    raise ValueError("Email inválido")
        
        validate = ValidateSignupHandler()
        create = CreateUserHandler()
        validate.set_next(create)
        
        validate.handle(context)
    """
    
    def __init__(self):
        """Inicializar handler."""
        self._next_handler = None
    
    def set_next(self, handler: 'SignupHandler') -> 'SignupHandler':
        """
        Establecer siguiente handler.
        
        Returns:
            SignupHandler: Para encadenamiento
        """
        self._next_handler = handler
        return handler
    
    def handle(self, context: SignupContext):
        """
        Ejecutar handler y continuar cadena.
        
        Args:
            context (SignupContext): Contexto de signup
        """
        self._handle(context)
        if self._next_handler:
            self._next_handler.handle(context)
    
    @abstractmethod
    def _handle(self, context: SignupContext):
        """Lógica específica (implementar en subclass)."""
        pass


# =========================================================
# REFRESH TOKEN HANDLERS
# =========================================================

class RefreshTokenHandler(ABC):
    """
    Clase base para handlers de refresco de tokens.
    
    Valida y genera nuevos access tokens usando refresh tokens.
    
    Cadena típica:
        ValidateRefreshTokenHandler
            ↓
        VerifyTokenSignatureHandler
            ↓
        GenerateNewAccessTokenHandler
            ↓
        LogTokenRefreshHandler
    """
    
    def __init__(self):
        """Inicializar handler."""
        self._next_handler = None
    
    def set_next(self, handler: "RefreshTokenHandler"):
        """Establecer siguiente handler."""
        self._next_handler = handler
        return handler
    
    def handle(self, context):
        """Ejecutar y continuar cadena."""
        self._handle(context)
        if self._next_handler:
            self._next_handler.handle(context)
    
    @abstractmethod
    def _handle(self, context):
        """Lógica específica (implementar en subclass)."""
        pass


# =========================================================
# ROLE CHANGE HANDLERS
# =========================================================

class RoleChangeHandler(ABC):
    """
    Clase base para handlers de cambio de rol.
    
    Valida y aplica cambios de rol de usuario.
    
    Cadena típica:
        VerifyPermissionsHandler
            ↓
        ValidateNewRoleHandler
            ↓
        UpdateUserRoleHandler
            ↓
        NotifyUserHandler
            ↓
        LogRoleChangeHandler
    
    Security:
        - Verificar que usuario actual es admin
        - Verificar que rol destino es válido
        - Auditar cambio de rol
    """
    
    def __init__(self):
        """Inicializar handler."""
        self._next_handler = None
    
    def set_next(self, handler: "RoleChangeHandler"):
        """Establecer siguiente handler."""
        self._next_handler = handler
        return handler
    
    def handle(self, context):
        """Ejecutar y continuar cadena."""
        self._handle(context)
        if self._next_handler:
            self._next_handler.handle(context)
    
    @abstractmethod
    def _handle(self, context):
        """Lógica específica (implementar en subclass)."""
        pass


# =========================================================
# CHANGE PASSWORD HANDLERS
# =========================================================

class ChangePasswordHandler(ABC):
    """
    Clase base para handlers de cambio de contraseña.
    
    Valida y aplica cambios de contraseña.
    
    Cadena típica:
        ValidateOldPasswordHandler
            ↓
        ValidateNewPasswordStrengthHandler
            ↓
        HashNewPasswordHandler
            ↓
        UpdateUserPasswordHandler
            ↓
        InvalidateSessionsHandler
            ↓
        SendPasswordChangeEmailHandler
            ↓
        LogPasswordChangeHandler
    
    Security:
        - Verificar contraseña anterior correcta
        - Validar fuerza de nueva contraseña
        - Invalidar todas las sesiones (logout en otros dispositivos)
        - Notificar al usuario del cambio
        - Auditar cambio
    """
    
    def __init__(self):
        """Inicializar handler."""
        self._next_handler = None
    
    def set_next(self, handler: "ChangePasswordHandler"):
        """Establecer siguiente handler."""
        self._next_handler = handler
        return handler
    
    def handle(self, context):
        """Ejecutar y continuar cadena."""
        self._handle(context)
        if self._next_handler:
            self._next_handler.handle(context)
    
    @abstractmethod
    def _handle(self, context):
        """Lógica específica (implementar en subclass)."""
        pass
