# Devosuit Haber Paneli

RSS kaynaklarından güncel teknoloji haberlerini toplayan; planlanan kategorideki adayları tek Gemini çağrısıyla puanlayan ve editör onayına sunulacak Türkçe Devosuit metni ile görsel kartı hazırlayan yönetim paneli.

X, Instagram ve Threads paylaşımı bu aşamada kapalıdır; metin ve görsel otomatik hazırlanır.

## Akış

```text
Plan saati → yalnız planlanan kategorinin RSS kaynakları → yerel ön eleme
    → en fazla 3 aday / tek Gemini çağrısı → en iyi güvenli aday
    → özgün Devosuit metni + 1200×675 kart → panel onayı
```

Kategoriler:

- `Girisim`
- `AI`
- `Teknoloji`
- `Yazilim`

İstanbul saatine göre günlük plan `10:00 Girisim`, `12:00 AI`, `14:00 Teknoloji`, `16:00 AI`, `18:00 Yazilim`, `20:00 Girisim` şeklindedir. Her dilimde yalnız ilgili kategori taranır. En fazla üç aday tek Gemini isteğinde puanlanır ve yalnız en yüksek puanlı güvenli aday için metin üretilir. Normal günlük üst sınır altı Gemini çağrısıdır.

Gemini her adayı `news`, `analysis`, `opinion`, `guide` veya `promotional` olarak sınıflandırır. Reklam içerikleri elenir. X, Threads ve Instagram metinleri, kaynak linkine ihtiyaç duymadan okunabilecek özgün Devosuit haberleri olarak ayrı hazırlanır. “Yazıya göre” gibi özetleme kalıpları kullanılmaz. Sayıların kaynakta bulunması yerel olarak denetlenir; görüş ve tahminlerin kesinleştirilmemesi promptta istenir.

`429` kota yanıtında bildirilen bekleme süresi uygulanır ve yalnız bir tekrar yapılır. Aynı yayın dilimi veritabanında benzersiz olduğu için uygulamanın yeniden başlaması ikinci bir Gemini isteği oluşturmaz.

Paneldeki **Sıradaki kategoriyi şimdi test et** düğmesi, saat beklemeden sıradaki İstanbul yayın diliminin kategorisini yeniden tarar ve aynı içerik hazırlama akışını çalıştırır. Her tıklama bir normal Gemini batch isteği kullanabilir; test kaydı ayrı tutulduğu için gerçek planlı dilimi tüketmez ve hiçbir sosyal ağda paylaşım yapmaz.

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

X, Threads ve Instagram için aynı Gemini isteğinde üç ayrı metin üretilir.
X için 240, Threads için 480 ve Instagram için 1800 karakter uygulama sınırı
vardır. Detay sayfasında üç metin ayrı düzenlenir ve birlikte onaylanır.
Görsel ortaktır. Eski tek metinli kayıtlar `Yeniden üret` ile dönüştürülebilir.
İstek sayısı değişmez; üç metin üretildiği için çıktı tokenı artar.

- RSS taramasını elle başlatma
- Çekilen haberleri kategori ve duruma göre filtreleme
- Gemini puanı, gerekçesi, temel gerçekler ve risk işaretleri
- Orijinal haber ile oluşturulan Devosuit metnini karşılaştırma
- Hazır içeriğin Devosuit görselini liste ve detay sayfasında görüntüleme
- 1200×675 PNG görselini indirme
- Metni düzenleme ve onaylama
- Adayı reddedip sıradaki adayı hazırlama
- Açık Gemini kuyruk durumu
- 10:00–20:00 yayın dilimlerinin canlı durumları
- Sıradaki yayın kategorisini saat beklemeden test etme

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
