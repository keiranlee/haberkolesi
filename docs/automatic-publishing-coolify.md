# Coolify: Blog → X ve Threads yayını

## Davranış

İstanbul saatine göre mevcut altı içerik dilimi korunur: 10:00 Girişim, 12:00 AI,
14:00 Teknoloji, 16:00 AI, 18:00 Yazılım, 20:00 Girişim. Dilimde içerik hazırlanır;
hazırlama bittikten sonra yayın kuyruğu çalışır. Paylaşım saati üretim ve medya
işleme süresine göre birkaç dakika gecikebilir. Her dakika kurtarma/tekrar kuyruğu
kontrol edilir. Yeni bir saat çizelgesi veya harici cron gerekmez.

Yalnız bu dilimlerde seçilen, asgari AI puanını geçen, yayınlanabilir ve risk
işareti olmayan haberler otomatik onaylanır. İki dilde blog ve görsel zorunludur.
Elle RSS taraması, puanlama ve **Sıradaki kategoriyi şimdi test et** otomatik yayın
yapmaz. Onaylı bir haberde **Blog ve açık sosyal kanallarda yayınla** ayrı bir
manuel komuttur; otomatik yayın anahtarından bağımsızdır.

Her haber önce blogda yayınlanır. Blog sayfası, Open Graph etiketleri ve görselin
herkese açık erişimi doğrulandıktan sonra X ve Threads'e **birer görselli kısa
özet + gerçek Türkçe blog bağlantısı** gönderilir. Eski devam metinleri panelde
kalır ancak yeni otomatik akış gönderi dizisi yayınlamaz. İngilizce blog aynı
yazının `/en/blog/<slug>` adresinde bulunur.

`AUTO_PUBLISH=true` **ve** panel anahtarı açık olmalıdır. `AUTO_PUBLISH=false`
genel kapatma anahtarıdır. Panel seçimi PostgreSQL'de saklanır, deploy sonrası
korunur. Duraklatma bir sonraki aşamayı durdurur; zaten gönderilmiş HTTP isteğini
geri alamaz. Kapalıyken başlayan içerik dilimleri sonradan otomatik yayınlanmaz.
Açıkken başlayan, tamamlanması deploy sırasında kesilen yayın hazırlıkları
24 saatlik kurtarma penceresinde ele alınır. Hazır yayın kuyruğu kalıcıdır.

## 1. Devosuit backend

Önce Devosuit backend değişikliklerini deploy edin. Frontend değişikliği yoktur.
Mevcut yönetici oturumu, blog düzenleme ve görsel yükleme uçları korunur.

Coolify environment variables:

```dotenv
NEWS_PUBLISH_TOKEN=<en az 32 karakter rastgele servis anahtarı>
NEWS_SITE_URL=https://devosuit.com
```

Anahtarı bir parola yöneticisiyle oluşturun; iki uygulamaya aynı değeri girin.
Kaynak koda, Git'e veya tarayıcıya koymayın. Mevcut S3/CDN ayarları kullanılır;
yeni bir depolama hesabı gerekmez. CDN'nin Meta sunucularından erişilebilir
olması gerekir; yalnız iç Docker adresi görsel URL'si olarak kullanılamaz.

Deployment öncesi mevcut veritabanı yedeğini alın. Backend'in mevcut migration
akışına şu komutun dahil olduğunu kontrol edin:

```sh
npm run db:deploy
```

Migration `BlogPost.automationKey` adlı nullable alanı ve benzersiz indeksini
ekler. Eski yazılar değişmez. Yeni Prisma istemcisi `npm run build` ile üretilir.
Migration'ı **yeni backend başlamadan önce** çalıştırın. Coolify'da tek seferlik
pre-deployment migration veya mevcut deployment akışınız kullanılabilir.
Canlı veritabanında `prisma migrate dev` / `db push` kullanmayın.

Yeni adresler:

- `GET /api/integrations/news/<64 karakter kaynak özeti>`: aynı aktarımın sonucunu alır.
- `PUT /api/integrations/news/<64 karakter kaynak özeti>`: `payload` JSON alanı
  ve `image` JPEG dosyası içeren multipart istekle iki dilde blog oluşturur.
- İkisi de `Authorization: Bearer <NEWS_PUBLISH_TOKEN>` ister.
- Eksik/çok kısa sunucu anahtarı: 503. Yanlış anahtar: 401.
- Servis anahtarı yönetici JWT'si değildir; kullanıcı, ayar, silme veya genel
  blog düzenleme yetkisi vermez. Aynı yazıya tekrar PUT mevcut sonucu döndürür.
- Yönetici sonradan metni düzenlerse tekrar aktarım değişikliği ezmez.
  Yönetici yazıyı yayından kaldırırsa entegrasyon 409 döndürür, tekrar yayınlamaz.

## 2. Haber Kölesi

Coolify environment variables:

```dotenv
AUTO_PUBLISH=false
DEVOSUIT_API_URL=https://BACKEND_ALAN_ADI/api
DEVOSUIT_SITE_URL=https://devosuit.com
DEVOSUIT_PUBLISH_TOKEN=<backend NEWS_PUBLISH_TOKEN ile aynı>
X_ENABLED=true
X_AUTO_PUBLISH=true
X_BACKEND=official
X_DAILY_LIMIT=8
THREADS_ENABLED=false
THREADS_USER_ID=
THREADS_ACCESS_TOKEN=
```

Mevcut X anahtarlarını koruyun. `DEVOSUIT_API_URL`, frontend adresi yerine
backend'in `/api` tabanıdır. Coolify projeleri aynı Docker ağına bağlıysa
`http://<gerçek-servis-adı>:5000/api` kullanılabilir; bu adresi gerçek ağ/servis
adına göre ayarlayın. Kamuya açık backend bağlantısında HTTPS kullanın.

Haber uygulamasının `/app/data` dizinini kalıcı volume olarak bağlayın.
Üretilen görseller ve yayın sırasında dondurulan JPEG'ler bu dizinde tutulur.
PostgreSQL de kalıcı depolama ve yedekleme kullanmalı. Çalışan container içine
yazılan `.env` yerine Coolify ortam değişkenlerini kullanın.

Yayın kuyruğu, kanal sonuçları ve panel ayarı açılışta eklenen bağımsız tablolarda
tutulur. PostgreSQL advisory lock birden fazla worker'ın aynı yayını eşzamanlı
göndermesini önler. AI içerik diliminin mevcut benzersiz kaydı korunur.

Kurulum tamamlanınca `AUTO_PUBLISH=true` yapıp deploy edin ve panel anahtarının
açık olduğunu doğrulayın. Threads kurulurken `THREADS_ENABLED=false` ile blog+X
çalışabilir. Kanal seçimi haber kuyruğa alınırken kaydedilir; Threads'i sonradan
açmak eski X/blog haberlerini geriye dönük topluca Threads'e göndermez.

## 3. Threads hesabını bağlama

Meta arayüzündeki isimler değişebilir; aşağıdaki yetkiler/API sözleşmesi esas alınır.

1. [Meta Developers](https://developers.facebook.com/) hesabınızda Threads
   kullanım senaryosuyla bir uygulama oluşturun.
2. Firma Threads hesabını uygulamanın izin verilen/test kullanıcılarına ekleyip
   hesap tarafında daveti/erişim iznini tamamlayın. Kendi hesabınızla geliştirme
   erişiminin yeterli olup olmadığını App Dashboard gösterir. İleride başka
   müşterilerin hesapları bağlanacaksa App Review/erişim düzeyi ayrıca ele alınır.
3. Hesabın yetkilendirmesinde en az `threads_basic` ve
   `threads_content_publish` izinlerini alın. Şifre ile giriş veya çerez otomasyonu yoktur.
4. Meta'nın token aracı veya OAuth akışıyla hesabın tokenını alın. OAuth
   kullanılıyorsa dönüş adresini uygulama ayarına birebir kaydedin. Bu sürümde
   panelde OAuth bağlantı ekranı yok; tek firma hesabı Coolify değişkenleriyle bağlanır.
5. Kısa ömürlü tokenı **uzun ömürlü tokena** dönüştürün. Meta'nın resmî Postman
   koleksiyonundaki **Get Long-Lived Access Token** isteğini kullanın:
   `GET https://graph.threads.net/access_token`, `grant_type=th_exchange_token`,
   `client_secret=<Threads uygulama gizlisi>` ve yetkilendirmede kısa ömürlü token.
   Yanıttaki `expires_in` değerini kontrol edin; normal uzun ömür 60 gündür.
6. Aynı tokenla `GET https://graph.threads.net/v1.0/me?fields=id,username` çağrısıyla
   hesabı doğrulayın. Dönen `id` → `THREADS_USER_ID`, uzun ömürlü token →
   `THREADS_ACCESS_TOKEN`. Uygulama ID'sini veya Instagram ID'sini yazmayın.
7. `THREADS_ENABLED=true` yapıp deploy edin. Token/uygulama gizlisini sohbet,
   Git, URL ekran görüntüsü veya loglarda paylaşmayın.

Uygulama ilk kayıttan bir gün sonra ve devamında yaklaşık haftalık aralıklarla
token yeniler. Yenilenmiş token PostgreSQL'de tutulur; yeniden deploy eski tokena
döndürmez. Coolify'daki token değişirse yeni değer esas alınır. Token süresi
dolmuşsa veya hesap erişimi iptal edilmişse tekrar yetkilendirin; süresi dolmuş
token yenilenemez. DB yedekleri bu erişim bilgisini de içerdiğinden gizli tutulmalı.

Kaynak: [Meta resmî Threads API koleksiyonu](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api).

## Hata ve kurtarma

- Blog başarısızsa sosyal kanallar bekler. Blog tamamlandıysa tekrar oluşturulmaz.
- X başarısız olsa bile Threads bağımsız denenir; başarılı kanallar tekrarlanmaz.
- Geçici hatalar en fazla 5 kez artan aralıklarla denenir; sonra panelde kalır.
- Gönderimden sonra ağ/DB koparsa sonuç **belirsiz** işaretlenebilir. Hesabı
  kontrol edip sayısal gönderi ID'si girin veya yayınlanmadığını açıkça doğrulayın.
  Kimliği verilen gönderi tekrar paylaşılmaz. Bu kontrol sessiz kopyaları önler.
- Ön kontrolü geçemeyen haberi düzeltip/onaylayıp detay sayfasından manuel
  yayınlayabilirsiniz. Yayına başlamış paketlerde içerik dondurulmuştur.
- Uygulama kapalıyken kaçırılan eski saatler otomatik toplu taranmaz. Mevcut
  scheduler gecikme toleransı korunur; kalıcı yayın işleri tekrar devam eder.

## Yayına alma kontrolü

Önce migration + backend, sonra haber uygulaması. Panelde ayarlar/eksik bilgiler
kontrol edilir. İlk gerçek yayın şirket hesabında ve sitede içerik oluşturacağı
için gerçek gönderim aşamasını bilerek başlatın. Yerel testler canlı Meta/X/S3
çağrısı yapmaz. Son kontrolde bir blogun TR/EN sayfaları, iki sosyal gönderideki
görsel ve bağlantı, panel sonuçları ve restart sonrası tekrar paylaşılmaması
doğrulanır.
