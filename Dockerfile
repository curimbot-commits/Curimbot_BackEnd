# Backend Dockerfile
FROM python:3.11-slim

# Crear el directorio de trabajo
WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código fuente
COPY . .

# Exponer el puerto de FastAPI
EXPOSE 8000
