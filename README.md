# 📰 Haber Kölesi — Otomatik Haber Botu

> Belirlenen haber siteleri (RSS) ve X (Twitter) hesaplarından veri toplayan, İngilizce kaynakları Türkçe'ye çeviren, Gemini AI ile skorlayıp filtreleyen ve X ile Threads'te otomatik paylaşım yapan profesyonel haber botu.

---

## 🏗️ Mimari

```
┌─────────────────────────────────────────────────────────────────┐
│                        HABER KÖLESİ                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │  RSS Feeds  │───▶│   Scraper    │───▶│  Deep Translator │    │
│  │  (17 kaynak)│    │  (Toplayıcı) │    │  (EN → TR çeviri)│    │
│  └─────────────┘    └──────┬───────┘    └────────┬─────────┘    │
│                            │                      │              │
│  ┌─────────────┐           │              ┌───────▼─────────┐   │
│  │  X Accounts │───▶───────┘              │   Gemini AI     │   │
│  │  (20 hesap) │                          │   (Skorlama)    │   │
│  └─────────────┘                          └───────┬─────────┘   │
│                                                   │              │
│                                           ┌───────▼─────────┐   │
│                                           │   PostgreSQL    │   │
│                                           │  (Haber Havuzu) │   │
│                                           └───────┬─────────┘   │
│                                                   │              │
│                                           ┌───────▼─────────┐   │
│                                           │   Publisher     │   │
│                                           │  (Paylaşıcı)   │   │
│                                           └──┬──────────┬───┘   │
│                                              │          │        │
│                                        ┌─────▼──┐  ┌───▼────┐   │
│                                        │   X    │  │Threads │   │
│                                        │(Tweet) │  │(Post)  │   │
│                                        └────────┘  └────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  APScheduler (AsyncIOScheduler, TZ=Europe/Istanbul)      │   │
│  │  • Toplayıcı: Her 1 saatte bir                           │   │
│  │  • Paylaşıcı: 07:00-00:00 arası her saat başı           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 📁 Proje Yapısı

```
haberkolesi/
├── main.py              # Ana giriş noktası, zamanlayıcı
├── scraper.py           # RSS + Twitter toplayıcı modülü
├── publisher.py         # X ve Threads paylaşıcı modülü
├── database.py          # PostgreSQL bağlantı havuzu ve CRUD
├── config.py            # Yapılandırma, kaynaklar, sabitler
├── requirements.txt     # Python bağımlılıkları
├── Dockerfile           # Docker imaj tanımı
├── .env.example         # Ortam değişkenleri şablonu
├── README.md            # Bu dosya
└── SETUP.md             # Kurulum ve dağıtım rehberi
```

## ⚡ Temel Özellikler

### 1. Toplayıcı (Collector)
- **17 RSS Feed** ve **20 X hesabından** haber toplama
- 4 kategori: `Startup`, `Teknoloji`, `AI`, `Yazilim`
- `trafilatura` ile zengin içerik çekme
- `deep-translator` ile otomatik İngilizce → Türkçe çeviri
- Türkçe kaynaklar otomatik algılanır, çeviri atlanır
- **Gemini 1.5 Flash** ile akıllı skorlama (8+ skor filtresi)

### 2. Paylaşıcı (Publisher)
- **Günde 18 gönderi** (07:00 - 00:00 arası her saat başı)
- **Dinamik kota yönetimi**: En az 10 gönderi `Startup` kategorisinden
- Aynı anda X ve Threads'te yayın
- Paylaşılan haberler otomatik işaretlenir

### 3. Güvenlik & Anti-Bot
- Rastgele User-Agent rotasyonu (`fake_useragent`)
- Gerçek tarayıcı header'ları (Chrome/Firefox/Edge)
- Rastgele gecikmeler (2-7 saniye jitter)
- Exponential backoff ile yeniden deneme (`tenacity`)
- Rate limit koruması (429 hata yönetimi)

### 4. Dayanıklılık
- Asenkron mimari (`asyncio`)
- PostgreSQL connection pooling (`asyncpg`)
- Graceful shutdown (SIGTERM/SIGINT)
- Kapsamlı loglama (dosya + konsol)
- Her hata izole edilir, sistem çökmez

## 🗄️ Veritabanı Şeması

```sql
CREATE TABLE haber_havuzu (
    id                SERIAL PRIMARY KEY,
    kaynak_url        TEXT UNIQUE NOT NULL,
    orjinal_metin     TEXT NOT NULL,
    cevrilmis_metin   TEXT NOT NULL,
    sosyal_medya_metni TEXT,
    kategori          VARCHAR(20) NOT NULL,  -- Startup | Teknoloji | AI | Yazilim
    skor              REAL NOT NULL DEFAULT 0.0,
    eklendigi_tarih   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paylasildi_mi     BOOLEAN NOT NULL DEFAULT FALSE,
    paylasilma_tarihi TIMESTAMPTZ
);
```

> **Not:** Bu şema, ileride FastAPI ile REST API ve admin paneli eklenmesine uygun şekilde tasarlanmıştır.

## 🔧 Hızlı Başlangıç

```bash
# 1. Repoyu klonla
git clone <repo-url> && cd haberkolesi

# 2. .env dosyasını oluştur
cp .env.example .env
# .env dosyasını düzenle ve API anahtarlarını gir

# 3. Docker ile çalıştır
docker build -t haberkolesi .
docker run -d \
  --name haberkolesi \
  --env-file .env \
  -v haberkolesi_data:/app/data \
  --restart unless-stopped \
  haberkolesi
```

Detaylı kurulum için [SETUP.md](SETUP.md) dosyasına bakın.

## 📊 Haber Kaynakları

| Kategori | RSS Kaynakları | X Hesapları |
|----------|---------------|-------------|
| **Startup** | Swipeline, eGirişim, Foundern, Entrepreneur, Forbes | @Swipeline_tr, @webrazzi, @egirisim, @TechCrunch, @Entrepreneur |
| **Teknoloji** | DonanimHaber, ShiftDelete, Technopat, The Verge, TechCrunch | @donanimhaber, @shiftdeletenet, @teknoblog, @verge, @WIRED |
| **AI** | The Rundown, AI News, VentureBeat, MarkTechPost | @turkiyeai, @yapayzekakafasi, @YapayZekaAI_, @AI_TechNews, @VentureBeat |
| **Yazılım** | Chip, InfoQ, Hacker News | @oncekiyazilimci, @teknoblog, @3rdemayaz, @github, @fireship_dev |

## 🛡️ Lisans

Bu proje özel kullanım içindir.
