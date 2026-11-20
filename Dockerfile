FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema + compilación
RUN mkdir -p /app/uploads && \
    apt-get update && apt-get install -y \
    build-essential \
    gcc \
    python3-dev \
    portaudio19-dev \
    libportaudio2 \
    libportaudiocpp0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Actualizar pip
RUN pip install --upgrade pip

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Detrás de Traefik (Dokploy): confiar en X-Forwarded-For para obtener la IP
# real del cliente (rate limiting, bloqueo de login, auditoría).
# Requisito: el puerto 8000 NO debe publicarse directamente a Internet;
# solo debe ser accesible a través del proxy. Si se publica, restringir
# FORWARDED_ALLOW_IPS a la IP/red del proxy.
ENV FORWARDED_ALLOW_IPS="*"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]