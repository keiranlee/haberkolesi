# Devosuit Haber Paneli — Kurulum ve Dağıtım Rehberi

Bu belge, Haber Kölesi botunun Docker ile nasıl çalıştırılacağını ve Coolify üzerinde nasıl deploy edileceğini adım adım anlatır.

---

## 📋 Ön Gereksinimler

- Docker 20.10+
- Docker Compose (opsiyonel)
- PostgreSQL 15+ veritabanı (harici veya Docker'da)
- Gemini API anahtarı ([Google AI Studio](https://aistudio.google.com/))
- Yönetim paneli parolası ve uzun, rastgele bir oturum anahtarı

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
| `ADMIN_PASSWORD` | Panel giriş parolası | Geliştirmede `1234` |
| `SESSION_SECRET` | İmzalı oturum anahtarı | Uzun rastgele değer |

### Opsiyonel Değişkenler

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Düşük maliyetli, structured output destekli güncel Gemini modeli |
| `GEMINI_MIN_SCORE` | `8.0` | Minimum skorlama eşiği |
| `GEMINI_MIN_INTERVAL_SECONDS` | `15` | Gemini istekleri arasındaki alt sınır |
| `CANDIDATE_LIMIT_PER_CATEGORY` | `3` | Tek Gemini çağrısına alınacak azami aday sayısı |
| `COOKIE_SECURE` | `false` | HTTPS dağıtımında mutlaka `true` olmalı |
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

Panel: `http://localhost:8000`

Panel; 10:00–20:00 arasındaki altı yayın diliminde yalnız planlanan kategoriyi tarar, en fazla üç adayı tek Gemini çağrısında değerlendirir ve kazanan için metin ile 1200×675 Devosuit görseli üretir. X, Instagram ve Threads paylaşımı kapalıdır.

X, Threads ve Instagram metinleri tek istekte ayrı hazırlanır. Kaynak linki veya “yazıya göre” kalıpları yerine doğrudan haber dili kullanılır. Sayısal ifadelerin kaynakta bulunması yerel olarak kontrol edilir; görüş ve tahminlerde kesinlik düzeyinin korunması istenir.

Paneldeki **Sıradaki kategoriyi şimdi test et** işlemi, bir sonraki yayın diliminin kategorisini anında tarayıp içerik hazırlar. Bu manuel işlem bir Gemini batch isteği kullanabilir; ayrı `test:` çalışma anahtarı sayesinde planlı görevin çalışmasını engellemez.

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
| `/app/data` | `haberkolesi_data` | Loglar ve smoke test raporları |

`/app/data` volume olarak bağlanırsa loglar ve manuel test raporları yeniden başlatmalarda korunur. Haberler ve AI iş kuyruğu PostgreSQL'de saklanır.

### 3.3 Ortam Değişkenleri

Coolify'da **Environment Variables** bölümüne `.env` dosyasındaki tüm değişkenleri ekleyin.

Canlı HTTPS ortamında oturum çerezini güvenli tutmak için `COOKIE_SECURE=true`
ayarlayın. Yerel HTTP geliştirmesinde `false` kalabilir.

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

# Haber ve durum özeti
SELECT COALESCE(ai_category, source_category) AS kategori,
       state,
       COUNT(*) AS adet
FROM news_items
GROUP BY COALESCE(ai_category, source_category), state;
```

### 4.3 Panel Kontrolü

Tarayıcıda `http://sunucu-adresi:8000` adresini açın. Geliştirme parolası `1234` ise panel güvenlik uyarısı gösterir; canlı ortamda `ADMIN_PASSWORD` değerini değiştirin.

---

## 5. Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `Veritabanı başlatılamadı` | `DATABASE_URL` değerini kontrol edin, PostgreSQL'in çalıştığından emin olun |
| `Gemini API hatası` | API anahtarını doğrulayın, kota limitlerini kontrol edin |
| `RSS parse hatası` | İlgili sitenin RSS feed URL'sini kontrol edin |
| `429 Too Many Requests` | Sistem Gemini'nin bildirdiği bekleme süresini uygular ve dilim isteğini yalnız bir kez tekrarlar; kota/billing durumunu Google AI Studio'dan kontrol edin |
| Panel açılmıyor | Container healthcheck ve `docker logs` çıktısını kontrol edin |

---

## 6. İleride Yapılacaklar

- [ ] Resmî X API ile onaylı gönderi yayını
- [ ] Instagram ve Threads API ile onaylı gönderi yayını
- [ ] Prometheus metrikleri
- [ ] Telegram bildirim entegrasyonu
- [ ] Semantik haber deduplikasyonu
