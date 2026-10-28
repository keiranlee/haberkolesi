# Açıklayıcı sosyal metinler ve blog

Amaç: Okuyana ne olduğunu, nasıl çalıştığını ve neden önemli olduğunu anlatan sosyal metinler; kaynakla desteklenen ayrıntıları bir araya getiren web sitesi blog metni.

- Ortak Gemini/OpenAI üretim şemasına `blog_title`, `blog_description`, `blog_text` ekle. Blog Markdown olarak, kaynağın yeterliliğine göre yaklaşık 500–800 kelime hedefler; sayı ve olgu uydurmaz. Az kaynak varsa daha kısa ve dürüst kalır.
- Blogu mevcut JSONB içerik paketinde sakla; eski üç platformlu kayıtlar düzenlenebilir kalır. Onay sırasında blog alanlarını koru ve düzenlemeleri kaydet.
- Panelde blog başlığı, arama açıklaması ve yazı alanları göster; Markdown indirme ve kopyalama sağla. Yayınlama bağlantısı eklenmez.
- X hesabı uzun gönderi yetkisi soruldu. Yanıt gelmediğinden standart hesapla uyumlu gönderi dizisi seçildi: X 250–275 karakter ilk gönderi + iki açıklayıcı devam; Threads 430–490 karakter ilk gönderi + bir veya iki açıklayıcı devam. Her parça platform sınırları içinde kalır. Instagram bütçesi korunur.
- X yayıncısı devam gönderilerini yanıt olarak bağlar; her başarılı gönderinin kimliğini saklar. Sonraki gönderi başarısız olursa tekrar deneme kalan yerden sürer. Canlı sosyal paylaşım yapılmaz.
- Açıklamayı jargonla doldurma; terimleri ilk kullanımda açıkla. Merak, somut faydayı öğrendikten sonra oluşsun; cevapsız kanca ile yetinme.
- Yeni blog için kaynak içerik bütçesini artır, OpenAI çıktı bütçesini yazıya yetecek şekilde ayarla. İstek sayısı korunur, uzun çıktı maliyetinin arttığı belirtilir.
- Karakter sınırlarını, sayı doğrulamasını, eski kayıtların onayını ve yeni blogun form/indirme akışını hedefli testlerle doğrula. Mevcut haber #148'de ücretli tek yeniden üretimle somut örnek hazırla; önbellekteki görsel kullanılır.

Uygulama tamamlandı. Canlı örnekte kısa onaylı olgulara aşırı bağlı kalma görüldüğünden tam kaynak kapsamı açıklaştırıldı; zengin kaynak için 500 kelime alt sınırı ve blog dahil özetçi kaynak kalıplarını reddetme eklendi. Örnek #148 üç metin denemesiyle hazırlandı ve editoryal kontrolden geçirildi; görsel tekrar üretilmedi. Son örnek 632 kelimelik blog, üç X gönderisi ve üç Threads gönderisi içeriyor. Web sitesine ya da sosyal platformlara yayın yapılmadı.

İnceleme, devam gönderisi uzunluk ihlallerinin düzeltme tekrarına girmesini istedi; ValueError, UnsafeDraftError olarak çevrildi ve regresyon testi eklendi. XPublisher kilidi asenkron paylaşım sırasında oluşturularak önceki Python 3.9 olay döngüsü test hatası da giderildi.

## İngilizce blog sürümü

Türkçe bloga ek olarak İngilizce başlık, arama açıklaması ve tam Markdown yazısı aynı üretimde hazırlanır. `blog_title_en`, `blog_description_en`, `blog_text_en` alanları mevcut JSONB pakette saklanır; eski tek dilli kayıtlar geçerlidir. İngilizce sayılar da kaynakla karşılaştırılır ve zengin kaynakta aynı 500 kelime alt sınırı uygulanır. Panelde diller ayrı düzenlenir/kopyalanır; `blog.md?lang=en` İngilizce dosyayı indirir. OpenAI çıktı tavanı iki tam bloga yer açmak için 10000 token oldu; tüketim gerçek çıktıya bağlıdır.

Örnek #148'in Türkçe içeriği değiştirilmeden ayrı bir çeviri isteğiyle 795 kelimelik İngilizce tam sürüm eklendi. Sayısal tutarlılık ve eşzamanlı düzenleme kontrolü yapıldı. Bu ek kapsamdan sonra 158 test geçti, 1 PostgreSQL entegrasyon testi ortam ayarı olmadığı için atlandı.
