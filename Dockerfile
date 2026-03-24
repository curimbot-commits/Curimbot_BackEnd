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

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]