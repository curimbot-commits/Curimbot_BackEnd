from app.services import security_service
from app.models import models
from fastapi import HTTPException
from app.services.handlers.base import SignupContext, SignupHandler


class CreateUserHandler(SignupHandler):
    def _handle(self, context: SignupContext):
        # Verificar si es el primer usuario
        is_first_user = context.db.query(models.User).count() == 0
        
        # Obtener roles de la base de datos
        if is_first_user:
            role = context.db.query(models.Role).filter(models.Role.name == "admin").first()
            if not role:
                # Crear rol admin si no existe
                role = models.Role(name="admin", description="Administrator role")
                context.db.add(role)
                context.db.flush()
        else:
            role = context.db.query(models.Role).filter(models.Role.name == "user").first()
            if not role:
                # Crear rol user si no existe
                role = models.Role(name="user", description="Regular user role")
                context.db.add(role)
                context.db.flush()

        new_user = models.User(
            name=context.user_data.name,
            email=context.user_data.email.lower(),
            password_hash=security_service.hash_password(context.user_data.password),
            role_id=role.id  # Usar role_id en lugar de role
        )
        context.db.add(new_user)
        try:
            context.db.commit()
            context.db.refresh(new_user)
        except Exception as e:
            context.db.rollback()
            raise HTTPException(status_code=500, detail=f"Error al crear el usuario: {str(e)}")

        context.new_user = new_user