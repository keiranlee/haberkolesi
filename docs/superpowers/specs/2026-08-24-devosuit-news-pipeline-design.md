# Devosuit Haber Üretim Sistemi Tasarımı

## Amaç

Devosuit için güncel teknoloji haberlerini toplayan, kategorize eden, Gemini ile puanlayan ve editörün inceleyebileceği özgün Türkçe X metinleri üreten tek uygulama kurulacak. İlk teslimde hiçbir içerik X'e gönderilmeyecek. Metin kalitesi panel üzerinden test edilip oturtulduktan sonra görsel üretimi, en son da X API yayını eklenecek.

## Teslim aşamaları

1. Haber toplama, ön filtreleme, Gemini puanlama, yeni metin üretme ve şifreli yönetim paneli.
2. Devosuit markalı haber görseli üretme ve panelde önizleme/onay.
3. Zamanlama ve resmî X API ile yayınlama.

İlk uygulama planı yalnızca birinci aşamayı kapsar. İkinci ve üçüncü aşamalar, metin kalitesi kullanıcı tarafından onaylandıktan sonra ayrı planlanır.

## Mimari

Sistem tek Docker uygulaması olarak çalışır:

- FastAPI HTTP uygulaması
- Jinja2 tabanlı, az JavaScript kullanan yönetim paneli
- APScheduler tabanlı arka plan görevleri
- PostgreSQL kalıcı veri deposu
- RSS haber toplayıcı
- Gemini istek kuyruğu ve hız sınırlayıcı

Tek uygulama yaklaşımı, mevcut Python projesini korur ve ilk sürümde Redis veya ayrı worker gerektirmez. Uzun süren toplama ve Gemini işlemleri HTTP isteğinin içinde çalışmaz; panel işi başlatır, arka plan görevi ilerlemeyi veritabanına yazar, panel durumu belirli aralıklarla yeniler.

## Birinci aşama veri akışı

1. Kullanıcı panelde **Haberleri Çek** düğmesine basar veya zamanlanmış toplama görevi çalışır.
2. RSS kaynaklarından güncel girdiler alınır.
3. Son 24 saat dışındaki girdiler, daha önce görülen URL'ler, URL varyasyonları ve aynı başlık/içerik tekrarları elenir.
4. Kaynağın yapılandırılmış kategorisi ilk kategori kabul edilir. Kategori başına en fazla beş yeni aday Gemini kuyruğuna alınır.
5. Gemini her adayı puanlar, kategoriyi doğrular, gerekçeyi ve haberdeki temel gerçekleri yapılandırılmış JSON olarak döndürür.
6. Adaylar kategori içinde puana göre sıralanır.
7. Test modunda kullanıcı bir kategori için **Aday Hazırla** dediğinde yalnızca en yüksek puanlı aday için Devosuit X metni üretilir. Başlangıçta ikinci aday için metin üretilmez.
8. Kullanıcı metni panelde inceler, düzenler, onaylar veya reddeder.
9. Kullanıcı reddederse aynı kategorideki sıradaki en yüksek puanlı aday için yeni metin üretilir.

Onay gelmemesi tek başına test modunda yeni Gemini isteği doğurmaz. Gelecekte zamanlanmış yayın etkinleştirildiğinde aday paylaşım saatinden 30 dakika önce hazırlanır, 15 dakika onay bekler ve süre dolarsa ikinci adaya geçer.

## Gemini kullanımı

Resmî model sayfasında güncel ve kararlı Flash modeli olarak gösterilen `gemini-3.7-flash` varsayılan modeldir. Model adı `GEMINI_MODEL` ortam değişkeniyle değiştirilebilir. Eski `google-generativeai` paketi yerine güncel Google Gen AI SDK kullanılacaktır.

Kullanıcının belirttiği dakikada beş istek sınırının altında kalmak için uygulama genelinde tek Gemini kuyruğu bulunur:

- İstekler arasında en az 15 saniye bulunur.
- Böylece uygulama en fazla dakikada dört istek başlatır.
- Eşzamanlı Gemini isteği sayısı birdir.
- `429` ve geçici `5xx` hataları artan bekleme süresiyle yeniden kuyruğa alınır.
- Kuyruk durumu veritabanında tutulur; uygulama yeniden başlarsa bekleyen işler kaybolmaz.
- Panel kalan aday, son istek zamanı, sonraki uygun istek zamanı ve hata durumunu gösterir.

Puanlama ile metin üretimi ayrı görevlerdir. Böylece elenen veya reddedilmeyen düşük sıralı adaylar için boşuna metin üretim isteği yapılmaz.

### Puanlama çıktısı

Gemini cevabı JSON şemasıyla doğrulanır:

- `score`: 0 ile 10 arasında sayı
- `category`: `AI`, `Girisim`, `Teknoloji` veya `Yazilim`
- `reason`: kısa puanlama gerekçesi
- `key_facts`: yalnızca kaynak içerikten çıkarılmış olgular
- `risk_flags`: doğrulanamayan iddia, reklam, söylenti veya eski haber uyarıları
- `is_publishable`: editoryal uygunluk kararı

JSON şemasına uymayan cevap yayın adayı olamaz; görev kontrollü biçimde yeniden denenir.

### Metin üretme kuralları

Üretilen metin:

- Türkçe ve doğal olmalı.
- Kaynakta bulunmayan bilgi eklememeli.
- Devosuit'in profesyonel teknoloji markası tonunda olmalı.
- Haber başlığını kopyalamak yerine yeniden anlatmalı.
- Gereksiz övgü, tıklama tuzağı ve kesin olmayan iddialardan kaçınmalı.
- Kaynak bağlantısı için yer bırakmalı.
- X karakter sınırına güvenli biçimde uymalı.
- En fazla iki ilgili hashtag kullanmalı.

Panelde **Yeniden Üret** işlemi açık bir kullanıcı eylemiyle çalışır ve yeni bir Gemini isteği tükettiğini önceden gösterir. Önceki metin sürümleri saklanır; kullanıcı sürümler arasında karşılaştırma yapabilir.

## Veri modeli

### `collection_batches`

Bir toplama çalışmasının başlangıç, bitiş, durum, bulunan haber ve hata sayılarını tutar.

### `news_items`

Kaynak URL, normalize URL, başlık, özet, tam içerik, kaynak, kaynak kategorisi, Gemini kategorisi, yayın tarihi, alınma tarihi, puan, gerekçe, temel gerçekler, riskler ve durum alanlarını tutar. Normalize URL benzersizdir.

### `generation_versions`

Bir haber için üretilen her metin sürümünü, kullanılan prompt/modeli, oluşturulma zamanını ve kullanıcı düzenlemesini tutar.

### `ai_jobs`

Puanlama ve metin üretme işlerinin `pending`, `running`, `completed`, `retry` veya `failed` durumlarını; deneme sayısı ile bir sonraki deneme zamanını tutar.

### `editor_actions`

Onay, ret ve metin düzenleme işlemlerini zaman damgasıyla kaydeder.

## Yönetim paneli

Panel mobil ve masaüstünde çalışan basit bir arayüzdür.

### Giriş

- Tek yönetici hesabı bulunur.
- İlk geliştirme parolası `1234` olur.
- Parola kaynak koda yazılmaz; `ADMIN_PASSWORD` ortam değişkeninden alınır.
- Oturum çerezi `HttpOnly`, `SameSite=Lax` ve canlı ortamda `Secure` olur.
- Canlı ortamda `1234` kullanılıyorsa panel belirgin güvenlik uyarısı gösterir.

### Ana ekran

- Haberleri Çek düğmesi
- Aktif toplama/Gemini işi ve ilerleme bilgisi
- Gemini kota sayacı ve sonraki istek zamanı
- Kategori ve durum özetleri
- Çekilen haber tablosu
- Kategori, puan, kaynak ve durum filtreleri

### Haber ayrıntısı

- Orijinal başlık, içerik ve kaynak bağlantısı
- Kaynak kategorisi ve Gemini kategorisi
- Gemini puanı, gerekçesi, temel gerçekleri ve risk uyarıları
- Üretilen Devosuit metni
- Metin düzenleme ve sürüm geçmişi
- Onayla, Reddet ve Yeniden Üret eylemleri
- Görsel bölümü için sonraki aşama yer tutucusu
- X yayını için devre dışı durum göstergesi

İlk aşamada **Onayla**, haberi yalnızca `approved` durumuna geçirir. Dış platforma istek göndermez.

## Kategori ve gelecekteki yayın sırası

Kategoriler veritabanında şu sabit değerlerle tutulur:

- `Girisim`
- `AI`
- `Teknoloji`
- `Yazilim`

Gelecekte İstanbul saat diliminde yayın planı şöyledir:

| Saat | Tercih edilen kategori |
|---|---|
| 10:00 | Girisim |
| 12:00 | AI |
| 14:00 | Teknoloji |
| 16:00 | AI |
| 18:00 | Yazilim |
| 20:00 | Girisim |

Sırası gelen kategoride yayınlanabilir haber yoksa günlük hedefleri bozmadan başka eksik kategori öne alınabilir. Günlük hedef iki girişim, iki AI, bir teknoloji ve bir yazılım haberidir.

Bu sıra birinci aşamada yalnızca panelde plan önizlemesi olarak görünür; otomatik yayın yapmaz.

## Hata yönetimi

- Bir RSS kaynağının hatası diğer kaynakları durdurmaz.
- Bozuk veya erişilemeyen kaynaklar panelde kaynak bazında gösterilir.
- İçeriği alınamayan haber Gemini'ye gönderilmez.
- Aynı anda ikinci toplama çalışması başlatılamaz.
- Gemini işi başarısızsa haber hata durumuna alınır; kullanıcı tekrar deneyebilir.
- Uydurma bilgi riski işaretlenen içerik otomatik aday olamaz.
- Veritabanı işlemleri atomik durum geçişleri kullanır.
- Loglarda API anahtarı, parola veya oturum çerezi bulunmaz.

## Test yaklaşımı

- URL normalizasyonu, 24 saat filtresi, tekrar tespiti ve kategori limitleri için birim testleri.
- Gemini JSON doğrulaması ve metin karakter sınırı için birim testleri.
- Sahte saat ile 15 saniyelik hız sınırlayıcı ve yeniden deneme testleri.
- RSS örnek dosyalarıyla toplama entegrasyon testleri.
- Test PostgreSQL veritabanıyla iş kuyruğu ve durum geçişi testleri.
- Panel giriş, liste, ayrıntı, düzenleme, onay ve ret akışları için HTTP testleri.
- Gerçek Gemini API çağrısı yalnızca açıkça çalıştırılan manuel smoke testinde kullanılır.
- Smoke test sonucu orijinal haber, puanlama ve üretilen metni karşılaştıran Markdown raporu oluşturur.

## İkinci aşama sınırı: görsel

Metin kalitesi onaylandıktan sonra `assets/logotek.svg` kullanılarak 1200×675 görseller tasarlanır. Ana arka plan `#201F4B`, marka vurguları logodaki turuncu gradyan olur. Görsel panelde önizlenip onaylanmadan yayınlanabilir duruma geçmez. Görsel üretim yöntemi ve şablonu ikinci aşama tasarımında kesinleştirilir.

## Üçüncü aşama sınırı: X yayını

Resmî X API entegrasyonu en son eklenir. Yalnızca metni ve görseli onaylanmış kayıtlar yayınlanabilir. Yayın işlemi idempotent olacak, X gönderi kimliği veritabanında tutulacak ve tekrar gönderim engellenecektir.

## Başarı ölçütleri

- Panel tek parola ile korunur.
- Yeni toplama işi panelden başlatılıp izlenebilir.
- Kategori başına en fazla beş yeni aday puanlama kuyruğuna girer.
- Gemini istekleri 15 saniyeden sık başlamaz.
- Puanlama ve metin üretme sonuçları panelde karşılaştırmalı görünür.
- İlk anda yalnızca birinci aday için metin oluşturulur.
- Ret işlemi sonraki adayı hazırlar.
- Onay işlemi dış paylaşım yapmaz.
- Hiçbir birinci aşama yolu X'e gönderi veya görsel üretmez.
