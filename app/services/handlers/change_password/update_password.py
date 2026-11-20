# app/services/handlers/change_password/update_password.py

from app.services import security_service

from app.services.handlers.change_password.context import ChangePasswordContext
from app.services.handlers.base import ChangePasswordHandler

class UpdatePasswordHandler(ChangePasswordHandler):
    """
    Actualiza el hash de la contraseña del usuario en la base de datos.
    """

    def _handle(self, context: ChangePasswordContext):
        # Reemplaza el hash de la contraseña actual con el hash de la nueva contraseña
        context.current_user.password_hash = security_service.hash_password(context.new_password)
        
        # Guarda los cambios en la base de datos
        context.db.commit()
