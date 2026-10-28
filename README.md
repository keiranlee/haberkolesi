# Devosuit Haber Paneli

## Otomatik blog, X ve Threads yayını

Planlı saatte seçilen güvenli haber, `AUTO_PUBLISH=true` ve panel anahtarı açıkken
editör beklemeden önce Devosuit blogunda, ardından açık X/Threads kanallarında
yayınlanır. Sosyal gönderiler **görsel + kısa Türkçe özet + gerçek blog linki**
içerir. Instagram yayın entegrasyonu yoktur. Eski içerik alanları okunabilir kalır.

Mevcut altı saatlik kategori çizelgesi korunur; manuel test işlemi paylaşım yapmaz.
Yeni akış birer sosyal gönderi yayınlar; oluşturulan devam metinleri gönderilmez.
Blog ve kanal sonuçları PostgreSQL'de ayrı saklanır. Tekrar denemeler başarılı
kanalları tekrarlamaz; belirsiz gönderim sonuçları panelde kontrol ister.

**Coolify kurulumu, Devosuit backend migration'ı, servis anahtarı ve Threads hesap
bağlantısı:** [Otomatik yayın rehberi](docs/automatic-publishing-coolify.md).

`X_AUTO_PUBLISH` yalnız otomatik işlerde X kanalının seçimini belirler. Genel
anahtar `AUTO_PUBLISH` ve kalıcı panel anahtarıdır. `THREADS_ENABLED` Threads
kanalını açar. Önce backend'i deploy edin; sonra erişim bilgilerini Coolify'a
girip otomatik yayını açın. `/app/data` ve PostgreSQL kalıcı olmalıdır.

RSS kaynaklarından güncel teknoloji haberlerini toplayan; planlanan kategorideki adayları seçili AI sağlayıcısıyla puanlayan ve editör onayına sunulacak sosyal metinler, iki dilli blog ve görsel hazırlayan yönetim paneli.

Varsayılan AI sağlayıcısı **OpenAI (ChatGPT)**'dır. `.env` içine `OPENAI_API_KEY` ekleyin; model varsayılanları `gpt-5.4-mini` ve `gpt-image-2` (low) şeklindedir. Gemini panelden seçilebilen alternatif olarak korunur ve isteğe bağlı `GEMINI_API_KEY` ile etkinleştirilir.

**Gemini / OpenAI seçimi.** Paneldeki AI sağlayıcısı kontrolüyle iki hat arasında geçiş yapılabilir. Varsayılan OpenAI puanlama, üç platform metni, iki dilli blog ve haberle ilgili yazısız görsel hazırlar. [Kurulum, maliyet ve deneme adımları](docs/openai-setup.md).

**Açıklayıcı içerik paketi:** Kazanan haber için X ve Threads ilk gönderileriyle devam metinleri, Instagram açıklaması, web sitesi blog başlığı, arama açıklaması ve ayrıntılı Markdown yazısı hazırlanır. Devam gönderileri bilgi ekler; blog yöntemi, ölçüm koşullarını, karşılaştırmaları ve kaynakta desteklenen sınırları açıklar. Zengin kaynaklarda en az 500 kelime, kısa kaynaklarda daha kısa içerik kullanılır. Blog panelden düzenlenebilir, kopyalanabilir ve indirilebilir. Mevcut üç platformlu taslaklarda Yeniden üret ile yeni alanlar oluşturulur.

Bloglar Türkçe ve İngilizce tam sürümleriyle aynı üretimde hazırlanır. Her dilin başlığı, arama açıklaması ve Markdown yazısı ayrı saklanır, düzenlenir ve indirilir. İngilizce sürüm Türkçenin bilgi kapsamını korur; sosyal gönderiler Türkçe kalır. Eski tek dilli bloglar okunabilir; Yeniden üret iki dilli paketi oluşturur.

Resmi X API v2 entegrasyonu mevcuttur; onaylanan haberler X paylaşımı etkinse görselli ilk gönderi ve bağlı açıklayıcı devamlarıyla paylaşılabilir.

## Akış

```text
Plan saati → yalnız planlanan kategorinin RSS kaynakları → yerel ön eleme
    → en fazla 3 aday / tek AI metin çağrısı → en iyi güvenli aday
    → sosyal metinler + Türkçe/İngilizce blog + ortak görsel → panel onayı
```

OpenAI seçiliyken yalnız kazanan haber için ayrıca bir yazısız görsel isteği yapılır. Metin yeniden üretiminde bu haberin mevcut OpenAI görseli kullanılır.

Kategoriler:

- `Girisim`
- `AI`
- `Teknoloji`
- `Yazilim`

İstanbul saatine göre günlük plan `10:00 Girisim`, `12:00 AI`, `14:00 Teknoloji`, `16:00 AI`, `18:00 Yazilim`, `20:00 Girisim` şeklindedir. Her dilimde yalnız ilgili kategori taranır. En fazla üç aday tek AI metin isteğinde puanlanır; yalnız en yüksek puanlı güvenli aday için içerik hazırlanır. Tekrarlar ve manuel denemeler hariç günlük altı metin isteği, OpenAI ile kazanan bulunursa ayrıca en fazla altı görsel isteği yapılır.

Gemini her adayı `news`, `analysis`, `opinion`, `guide` veya `promotional` olarak sınıflandırır. Reklam içerikleri elenir. X, Threads ve Instagram metinleri, kaynak linkine ihtiyaç duymadan okunabilecek özgün Devosuit haberleri olarak ayrı hazırlanır. “Yazıya göre” gibi özetleme kalıpları kullanılmaz. Sayıların kaynakta bulunması yerel olarak denetlenir; görüş ve tahminlerin kesinleştirilmemesi promptta istenir.

`429` kota yanıtında bildirilen bekleme süresi uygulanır ve yalnız bir tekrar yapılır. Aynı yayın dilimi veritabanında benzersiz olduğu için uygulamanın yeniden başlaması ikinci bir Gemini isteği oluşturmaz.

Paneldeki **Sıradaki kategoriyi şimdi test et** düğmesi, saat beklemeden sıradaki İstanbul yayın diliminin kategorisini yeniden tarar ve aynı içerik hazırlama akışını çalıştırır. Her tıklama bir normal Gemini batch isteği kullanabilir; test kaydı ayrı tutulduğu için gerçek planlı dilimi tüketmez ve hiçbir sosyal ağda paylaşım yapmaz.

## Hızlı başlangıç

```bash
cp .env.example .env
```

`.env` içinde en az şu değerleri değiştirin:

```dotenv
OPENAI_API_KEY=your_real_key
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
- Onaylanan haberi panelden tek tıkla resmi X hesabında paylaşma (`X'te Şimdi Paylaş`)
- Planlanan yayın diliminde onaylı haberleri otomatik olarak X'te tweetleme (`X_AUTO_PUBLISH=true`)

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
