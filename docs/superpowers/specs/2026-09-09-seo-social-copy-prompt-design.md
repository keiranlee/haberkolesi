# SEO Odaklı Sosyal Medya Metni Prompt Tasarımı

## Amaç

Gemini, seçilen haber için X, Instagram ve Threads'te ortak kullanılabilecek tek bir özgün Türkçe metin üretecektir. Metin; web sayfası SEO metni gibi anahtar kelime doldurmayacak, sosyal platformlardaki arama ve keşfedilebilirlik için haberin gerçek konusunu açıklayan doğal anahtar ifadeler kullanacaktır.

Bu değişiklik Gemini çağrı sayısını artırmayacaktır. Aday puanlama, kazanan seçimi ve kazanan metni mevcut tek yapılandırılmış istekte kalacaktır.

## İçerik Türü ve Haber Değeri

Gemini her aday için aşağıdaki içerik türlerinden birini döndürecektir:

- `news`: Doğrulanabilir yeni olay, ürün, yatırım, sürüm veya araştırma.
- `analysis`: Güncel bir gelişmeye dayanan açıklayıcı analiz.
- `opinion`: Yazar görüşü veya kişisel yorum.
- `guide`: Nasıl yapılır, tavsiye veya zamandan bağımsız rehber.
- `promotional`: Reklam, sponsorlu içerik veya ürün tanıtımı ağırlıklı metin.

`opinion` ve `guide` içerikleri haberlerden daha düşük haber değeri alacaktır; ancak somut, kaynak metinde doğrulanabilir veri taşıyor ve kalite eşiğini geçiyorsa seçilebilir. Böyle bir metinde içerik türü açık atıfla belirtilmelidir. `promotional` içerikler otomatik yayın adayı olamaz. `analysis` yalnız açık, güncel ve doğrulanabilir bir gelişmeye dayanıyorsa yayınlanabilir. Bu karar `is_publishable` alanına yansıtılacak ve uygulama tarafından ayrıca doğrulanacaktır.

## Anahtar İfade Üretimi

Kazanan aday için Gemini şunları döndürecektir:

- `primary_keyword`: Haberin gerçek arama niyetini anlatan 2–5 kelimelik ana ifade.
- `secondary_keywords`: Birbirini tekrar etmeyen 1–3 destekleyici ifade.
- `text`: Tek sosyal medya metni.

Ana ve destekleyici ifadeler kaynak başlığı ile metninden çıkarılacaktır. Marka, ürün, sektör, teknoloji veya haberin ölçülebilir etkisi önceliklidir. Kaynakta bulunmayan trend, sonuç veya ticari iddia anahtar ifade olarak eklenemez.

Metin `primary_keyword` ifadesini doğal biçimde içerecektir. En az bir destekleyici ifade, anlamı bozmadan kullanılacaktır. Aynı kelimenin gereksiz tekrarına ve hashtag içinde anahtar kelime doldurmaya izin verilmeyecektir.

## Metin Kuralları

- Çıktı yalnızca bir sosyal medya metni olacaktır.
- Uzunluk 180–240 karakter olacaktır.
- İlk cümle haberin en güçlü, doğrulanabilir unsurunu açıkça verecektir.
- İkinci cümle etkisini veya bağlamını açıklayacaktır.
- Türkçe karakterler doğru kullanılacaktır; `şirket`, `müşteri`, `çevrim içi`, `görüşme` gibi kelimeler ASCII harflere indirgenmeyecektir.
- Kaynak başlığı kopyalanmayacak veya yalnızca kelime sırası değiştirilerek yeniden yazılmayacaktır.
- Tıklama tuzağı, ünlem ağırlıklı reklam dili ve `devrim niteliğinde`, `oyunun kurallarını değiştiriyor` gibi kaynaksız değerlendirmeler kullanılmayacaktır.
- En fazla iki ilgili hashtag kullanılacaktır. Hashtagler metnin ana konusu veya sektörünü temsil edecektir.
- Kaynak bağlantısı metne eklenmeyecek; platform paylaşım katmanı daha sonra ekleyecektir.

## Sayı ve İddia Doğruluğu

Rakamların anlamı korunacaktır. Kaynak `alıcıların %68'i çevrim içi araştırmayı tercih ediyor` diyorsa metin bunu `%68'i araştırma yapıyor` şeklinde kesin bir davranışa dönüştüremez.

Görüş yazısı, katkıda bulunan yazar yazısı veya kaynağı belirtilmemiş sektör verisi kullanıldığında metin `yazıya göre`, `aktarılan sektör verisine göre` veya eşdeğer bir atıf içerecektir. Kaynağın korelasyon olarak sunduğu etki, nedensellik gibi yazılamaz; `etkileyebilir` ifadesi `doğrudan etkiliyor` şeklinde güçlendirilemez.

Gemini, metinde kullanılan kaynak olgularını mevcut `used_facts` alanında birebir döndürmeye devam edecektir.

## Yapılandırılmış Çıktı

Her aday değerlendirmesine `content_type` alanı eklenecektir. Kazanan bulunan cevapta mevcut alanlara ek olarak `primary_keyword` ve `secondary_keywords` bulunacaktır.

Güvenli kazanan yoksa metin, görsel metinleri ve anahtar ifade alanları boş olacaktır. Kazanan varsa bütün alanlar zorunludur.

## Yerel Doğrulama

Uygulama Gemini cevabını kaydetmeden önce şunları kontrol edecektir:

- `promotional` aday seçilemez; `opinion` ve `guide` adayları somut veri, kalite eşiği ve açık atıf koşullarını sağlamalıdır.
- Metin 180–240 karakter aralığındadır.
- Metinde en fazla iki hashtag vardır.
- Ana ifade metinde büyük/küçük harf farkı gözetmeden bulunur.
- Destekleyici ifadelerden en az biri metinde bulunur.
- Kaynak başlığıyla mevcut yüzde 80 benzerlik sınırı aşılmaz.
- Kaynakta Türkçe karakter gerektiren yaygın kelimelerin ASCII biçimleri kullanılmışsa cevap reddedilir.
- Metindeki yüzde, para ve diğer sayısal ifadeler kaynak içerikte bulunmalıdır.
- `used_facts` yalnız seçilen adayın onaylı gerçeklerinden oluşur.

Geçersiz cevap mevcut politika doğrultusunda yalnız bir kez yeniden denenecek; ikinci başarısızlık dilim hatası olarak kaydedilecektir.

## Örnek Kabul Kriteri

Kaynak, B2B alıcılarının yüzde 68'inin satış temsilcisiyle iletişime geçmeden önce çevrim içi araştırmayı tercih ettiğini ve zayıf dijital itibarın müşteri edinme maliyetini artırabileceğini savunan bir görüş yazısıysa haber türüne göre puan cezası alacaktır. Yalnız somut verileri doğru atıf ve olasılık diliyle aktarabiliyor ve genel kalite eşiğini geçiyorsa seçilebilir.

Editör tarafından manuel üretim istenirse doğru metin şu özellikleri taşımalıdır:

- `B2B satış`, `dijital itibar` veya `müşteri edinme maliyeti` gibi somut ifadeler.
- Yüzde 68 verisinin `tercih ediyor` anlamını koruması.
- Maliyet etkisinin olasılık diliyle verilmesi.
- En fazla iki konu odaklı hashtag.

## Test Stratejisi

- Tanıtım içeriğinin yüksek puana rağmen kazanan olamaması.
- Görüş ve rehber içeriklerinin puan cezası alması; somut veri ve açık atıf olmadan seçilememesi.
- Gerçek haber veya güncel analizin seçilebilmesi.
- Ana ifadesi bulunmayan metnin reddedilmesi.
- Destekleyici ifade içermeyen metnin reddedilmesi.
- 180 karakterden kısa ve 240 karakterden uzun metnin reddedilmesi.
- Üçten fazla hashtag içeren metnin reddedilmesi.
- Kaynakta bulunmayan sayısal iddianın reddedilmesi.
- Kaynaktaki `tercih` ifadesini kesin davranışa çeviren örnek cevabın reddedilmesi.
- Türkçe karakterleri ASCII'ye indirgeyen metnin reddedilmesi.
- Başlığı kopyalayan metnin reddedilmesi.
- Geçerli metnin tek Gemini çağrısıyla kabul edilmesi.

## Kapsam Dışı

- Web sayfası için meta title, meta description veya uzun SEO makalesi üretimi.
- Birden fazla metin alternatifi üretimi.
- Platform başına ayrı metin üretimi.
- X, Instagram veya Threads API paylaşımı.
