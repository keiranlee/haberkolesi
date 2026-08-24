# ═══════════════════════════════════════════════════════════
# Haber Kölesi — Docker İmajı
# ═══════════════════════════════════════════════════════════
FROM python:3.11-slim AS base

# Sistem bağımlılıkları
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini
WORKDIR /app

# Bağımlılıkları önce kopyala (Docker cache optimizasyonu)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY . .

# Kalıcı veri dizini (Volume mount noktası)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# Sağlık kontrolü
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/health || exit 1

# Uygulamayı başlat
CMD ["python", "-u", "main.py"]
