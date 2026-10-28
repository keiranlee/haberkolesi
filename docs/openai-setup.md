# Gemini / OpenAI sağlayıcı seçimi

Varsayılan sağlayıcı **OpenAI (ChatGPT)**'dır. Puanlama ve metin üretiminde `gpt-5.4-mini`, yazısız görselde `gpt-image-2` kullanılır. Yeni veritabanı OpenAI seçimiyle başlar; panelden açıkça kaydedilmiş seçim yeniden başlatmalarda korunur. Ana panelde **AI sağlayıcısı** alanından Gemini veya OpenAI seçip **Seçimi kaydet** düğmesine basabilirsiniz. Gemini alternatifi yalnız `GEMINI_API_KEY` tanımlıysa etkinleşir; OpenAI kullanmak için Gemini anahtarı gerekmez. İş başladıktan sonra sağlayıcısı sabitlenir; kuyruktaki hata tekrarları da aynı sağlayıcıyı kullanır. Yeni işler yeni seçimi kullanır. Hata durumunda başka sağlayıcıya sessiz geçiş yapılmaz.

## Anahtar ekleme

Mevcut `.env` dosyasına aşağıdaki alanları ekleyin. Dosyayı `.env.example` ile değiştirmeyin; mevcut Gemini ve veritabanı ayarlarını koruyun.

```dotenv
OPENAI_API_KEY=buraya_kendi_anahtarinizi_yazin
OPENAI_MODEL=gpt-5.4-mini
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_IMAGE_QUALITY=low
```

Bağımlılıkları `pip install -r requirements.txt` ile kurup uygulamayı yeniden başlatın (`python main.py`, mevcut çalıştırma yönteminize uygun biçimde). Panelde OpenAI seçilebilir hale gelir. Anahtarı sohbete göndermeyin, Git'e eklemeyin. Anahtarın bulunması doğrulandığı anlamına gelmez: geçerliliği, bakiye ve model erişimi ilk API isteğinde kontrol edilir. OpenAI tarafında görsel model erişimi/kuruluş doğrulaması gerekebilir.

## İşleyiş ve maliyet sınırı

- Zamanlanmış akışta mevcut kategori filtresi ve en fazla üç aday korunur. Tek metin isteğinde adaylar puanlanır ve kazanan için üç platform metni hazırlanır.
- Metinler mevcut kaynak doğruluğu ve karakter sınırı kontrollerinden geçer. Kaynak metnin içindeki talimatlar veri olarak değerlendirilir.
- Her kazanan haber artık ayrıca blog başlığı, arama açıklaması ve ayrıntılı Markdown yazısı üretir. Blog için yeterli kaynak varsa 500–800 kelime hedeflenir; eksik bilgiler uydurulmaz. Panelden düzenlenebilir ve `.md` olarak indirilebilir.
- Türkçe blogun yanında `blog_title_en`, `blog_description_en`, `blog_text_en` alanlarında İngilizce tam sürüm hazırlanır. İki dil aynı olguları ve ayrıntı kapsamını korur; her dil ayrı düzenlenebilir, kopyalanabilir ve Markdown indirilebilir (`blog.md?lang=en`). Aynı metin isteğinde üretilir; ikinci dil çıktı tokenlarını artırır. Önceki tek dilli kayıtlar kullanılabilir kalır.
- Standart hesaplara uygun açıklayıcı X ve Threads dizileri hazırlanır: ilk gönderi ve ayrı devam metinleri. Her boş satır yeni devam gönderisidir. X gönderisi başına 280, Threads gönderisi başına 500 karakter sınırı uygulanır. X yayınlama açık olduğunda devamlar yanıt olarak bağlanır; kısmi hata sonrasında kayıtlı gönderi kimliklerinden devam edilir. Threads yayınlama entegrasyonu bu değişiklikte eklenmedi.
- Uzun blog ve sosyal devam metinleri daha fazla çıktı tokenı tüketir. Önceki kısa içerik için verilen yaklaşık $3/ay tahmini yeni içerik paketinin sabit maliyeti değildir; gerçek maliyet kullanım panelinden ölçülmelidir.
- OpenAI görselleri `gpt-image-2`, `low`, `1536x1024`, tek PNG olarak istenir. Başlık ve desteklenen bilgiye dayalı yazısız, logosuz temsili illüstrasyon talimatı kullanılır. Modelin hiçbir zaman yazı üretmeyeceği garanti edilemez; yayın öncesi editör kontrolü gerekir.
- Gemini'nin yerel yazılı kart üretimi değişmez. OpenAI görselleri `data/images/<haber-id>-openai.png` dosyasına kaydedilir; Gemini kartları ezilmez.
- **Yeniden üret** metinleri yeniler. Bu haberin OpenAI görseli varsa tekrar ücretli görsel isteği yapılmaz. İlk OpenAI üretiminde görsel oluşturulur. Görsel kalite/model ayarını değiştirmek mevcut önbelleği yenilemez.
- Görsel API isteği başarısız olursa yeniden üretimde önceki metin korunur ve iş hatası gösterilir.
- Düşük görsel kalitesiyle aylık yaklaşık $3 önceki varsayımlara dayalı tahmindir, garanti veya harcama limiti değildir. Uzun girdiler, doğrulama tekrarları, yeniden üretimler ve API fiyat değişiklikleri maliyeti etkiler. OpenAI projesinde ayrıca kullanım bütçesi/uyarıları ayarlayın.
- Sosyal platformlara paylaşım ayarları bu özellikle değiştirilmez.

## Anahtar eklendikten sonra deneme

1. Panelde OpenAI seçip kaydedin.
2. Var olan bir taslakta **Yeniden üret** düğmesine basın.
3. İş tamamlanınca X, Threads, Instagram metinlerini ve yazısız görseli kontrol edin.
4. Gemini'ye dönüp yeni bir iş başlatarak eski hattın hâlâ çalıştığını kontrol edin.

Geliştirme testleri sahte HTTP yanıtlarıyla, ücretli çağrı olmadan çalışır. Gerçek metin/görsel kalitesi ve hesap erişimi API anahtarıyla ayrıca denenmelidir.

API sözleşmeleri: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Image generation](https://developers.openai.com/api/reference/python/resources/images/methods/generate).
