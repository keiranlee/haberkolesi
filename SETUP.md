# 🚀 Haber Kölesi — Kurulum ve Dağıtım Rehberi

Bu belge, Haber Kölesi botunun Docker ile nasıl çalıştırılacağını ve Coolify üzerinde nasıl deploy edileceğini adım adım anlatır.

---

## 📋 Ön Gereksinimler

- Docker 20.10+
- Docker Compose (opsiyonel)
- PostgreSQL 15+ veritabanı (harici veya Docker'da)
- Gemini API anahtarı ([Google AI Studio](https://aistudio.google.com/))
- X (Twitter) hesap bilgileri
- Threads (Instagram) hesap bilgileri

---

## 1. Ortam Değişkenleri

`.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun:

```bash
cp .env.example .env
```

### Zorunlu Değişkenler

| Değişken | Açıklama | Örnek |
|----------|----------|-------|
| `DATABASE_URL` | PostgreSQL bağlantı dizesi | `postgres://user:pass@host:5432/havuz` |
| `GEMINI_API_KEY` | Google Gemini API anahtarı | `AIzaSy...` |
| `X_USERNAME` | X (Twitter) kullanıcı adı | `haberkolesi` |
| `X_EMAIL` | X hesap e-postası | `bot@example.com` |
| `X_PASSWORD` | X hesap şifresi | `********` |
| `THREADS_USERNAME` | Threads kullanıcı adı | `haberkolesi` |
| `THREADS_PASSWORD` | Threads şifresi | `********` |

### Opsiyonel Değişkenler

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `GEMINI_MODEL` | `gemini-1.5-flash` | Kullanılacak Gemini modeli |
| `GEMINI_MIN_SCORE` | `8.0` | Minimum skorlama eşiği |
| `DB_MIN_POOL` | `2` | Minimum DB bağlantı sayısı |
| `DB_MAX_POOL` | `10` | Maksimum DB bağlantı sayısı |
| `MIN_DELAY` | `2.0` | Minimum gecikme (saniye) |
| `MAX_DELAY` | `7.0` | Maksimum gecikme (saniye) |
| `DATA_DIR` | `/app/data` | Kalıcı veri dizini |

---

## 2. Docker ile Çalıştırma

### 2.1 İmaj Oluşturma

```bash
docker build -t haberkolesi:latest .
```

### 2.2 Tek Komutla Çalıştırma

```bash
docker run -d \
  --name haberkolesi \
  --env-file .env \
  -v haberkolesi_data:/app/data \
  --restart unless-stopped \
  haberkolesi:latest
```

### 2.3 Docker Compose (Opsiyonel)

Proje kök dizinine `docker-compose.yml` oluşturun:

```yaml
version: "3.8"

services:
  haberkolesi:
    build: .
    container_name: haberkolesi
    env_file: .env
    volumes:
      - haberkolesi_data:/app/data
    restart: unless-stopped
    depends_on:
      - postgres

  postgres:
    image: postgres:16-alpine
    container_name: haberkolesi_db
    environment:
      POSTGRES_DB: havuz
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: your_secure_password
    volumes:
      - pg_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

volumes:
  haberkolesi_data:
  pg_data:
```

Çalıştırma:
```bash
docker compose up -d
```

---

## 3. Coolify Üzerinde Dağıtım

### 3.1 Proje Oluşturma

1. Coolify panelinde **New Resource** → **Docker** seçin.
2. Git repo URL'sini girin veya **Dockerfile** seçeneğini kullanın.

### 3.2 Volume Yapılandırması

Coolify'da uygulama ayarlarından **Persistent Storage** bölümüne gidin:

| Container Yolu | Host Yolu / Volume Adı | Açıklama |
|----------------|------------------------|----------|
| `/app/data` | `haberkolesi_data` | Çerez dosyaları, loglar |

> ⚠️ **Önemli:** `/app/data` dizini volume olarak bağlanmalıdır. Bu dizin:
> - `x_cookies.json` — X oturum çerezleri
> - `threads_session.json` — Threads oturum verisi
> - `app.log` — Uygulama logları
> 
> Volume bağlanmazsa, container yeniden başlatıldığında oturum bilgileri kaybolur ve yeniden giriş gerekir.

### 3.3 Ortam Değişkenleri

Coolify'da **Environment Variables** bölümüne `.env` dosyasındaki tüm değişkenleri ekleyin.

### 3.4 Sağlık Kontrolü

Dockerfile'da tanımlı healthcheck, Coolify'ın container durumunu izlemesi için kullanılır.
Alternatif olarak Coolify'da özel healthcheck tanımlayabilirsiniz.

### 3.5 Kaynak Limitleri (Önerilen)

| Kaynak | Değer |
|--------|-------|
| CPU | 0.5 - 1.0 core |
| RAM | 256MB - 512MB |
| Disk | Volume'a bağlı |

---

## 4. İlk Çalıştırma Sonrası

### 4.1 Log Takibi

```bash
# Docker
docker logs -f haberkolesi

# Log dosyası (volume içinde)
docker exec haberkolesi tail -f /app/data/app.log
```

### 4.2 Veritabanı Kontrolü

```bash
# Container içinden
docker exec -it haberkolesi_db psql -U postgres -d havuz

# Havuz durumu
SELECT kategori, COUNT(*) as adet, 
       COUNT(*) FILTER (WHERE paylasildi_mi = TRUE) as paylasildi
FROM haber_havuzu 
GROUP BY kategori;
```

### 4.3 X Oturum Yenileme

X (Twitter) oturumu zaman zaman expire olabilir. Bu durumda:

1. Container'daki `/app/data/x_cookies.json` dosyasını silin.
2. `.env`'de `X_USERNAME`, `X_EMAIL`, `X_PASSWORD` değerlerinin doğru olduğundan emin olun.
3. Container'ı yeniden başlatın: `docker restart haberkolesi`

---

## 5. Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `Veritabanı başlatılamadı` | `DATABASE_URL` değerini kontrol edin, PostgreSQL'in çalıştığından emin olun |
| `Gemini API hatası` | API anahtarını doğrulayın, kota limitlerini kontrol edin |
| `X giriş hatası` | Çerez dosyasını silip yeniden başlatın, 2FA kapalı olmalı |
| `RSS parse hatası` | İlgili sitenin RSS feed URL'sini kontrol edin |
| `429 Too Many Requests` | Sistem otomatik backoff yapar, `MIN_DELAY`/`MAX_DELAY` artırılabilir |
| `Threads payla\u015f\u0131m hatas\u0131` | Oturum dosyasını silip yeniden başlatın |

---

## 6. İleride Yapılacaklar

- [ ] FastAPI ile REST API endpoint'leri
- [ ] Web admin paneli (React/Vue)
- [ ] Prometheus metrikleri
- [ ] Telegram bildirim entegrasyonu
- [ ] Haber deduplikasyonu (semantik benzerlik)
