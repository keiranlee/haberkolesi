# Devosuit Haber Paneli

RSS kaynaklarından güncel teknoloji haberlerini toplayan, Gemini ile kategorize edip puanlayan ve editör onayına sunulacak Türkçe Devosuit metinleri hazırlayan yönetim paneli.

Bu branch birinci aşamadır. Görsel üretimi ve X paylaşımı kapalıdır.

## Akış

```text
RSS → 24 saat filtresi → tekrar temizleme → kategori başına 5 aday
    → Gemini puanı → en iyi aday → Devosuit metni → panel onayı
```

Kategoriler:

- `Girisim`
- `AI`
- `Teknoloji`
- `Yazilim`

Gemini istekleri tek kuyrukta ve en az 15 saniye arayla başlatılır. İlk anda yalnız en yüksek puanlı aday için metin üretilir. Ret verilirse sıradaki aday hazırlanır.

## Hızlı başlangıç

```bash
cp .env.example .env
```

`.env` içinde en az şu değerleri değiştirin:

```dotenv
GEMINI_API_KEY=your_real_key
SESSION_SECRET=your_long_random_secret
ADMIN_PASSWORD=1234
```

Docker ile:

```bash
docker compose up --build
```

Panel: `http://localhost:8000`

Geliştirme parolası `1234` kullanıldığında panel uyarı gösterir. Canlı ortamda mutlaka değiştirin.

## Panel özellikleri

- RSS taramasını elle başlatma
- Çekilen haberleri kategori ve duruma göre filtreleme
- Gemini puanı, gerekçesi, temel gerçekler ve risk işaretleri
- Orijinal haber ile oluşturulan Devosuit metnini karşılaştırma
- Metni düzenleme ve onaylama
- Adayı reddedip sıradaki adayı hazırlama
- Açık Gemini kuyruk durumu
- Gelecekteki 10:00–20:00 kategori planı önizlemesi

Onay işlemi yalnız veritabanı durumunu değiştirir. X API çağrısı yapmaz.

## Testler

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -v
```

Gerçek PostgreSQL entegrasyon testi için:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/haberkolesi_test \
  .venv/bin/python -m pytest tests/test_repositories.py -v
```

## Gerçek RSS + Gemini smoke testi

Bu komut gerçek API kotası kullanır. `--live` olmadan ağ veya Gemini çağrısı yapılmaz.

```bash
.venv/bin/python smoke_test.py \
  --live \
  --category Girisim \
  --output data/gemini-smoke-report.md
```

Rapor; orijinal haber, Gemini puanı, gerekçe, riskler ve yeni Devosuit metnini yan yana gösterir. Görsel veya X gönderisi oluşturmaz.

## Güvenlik notu

Eski `.env.example` içinde gerçek görünümlü bir PostgreSQL parolası bulunuyordu. Örnek dosya temizlendi. Bu parola herhangi bir ortamda kullanılıyorsa döndürülmelidir; eski değer Git geçmişinde kalır.

Detaylı dağıtım bilgisi: [SETUP.md](SETUP.md)
