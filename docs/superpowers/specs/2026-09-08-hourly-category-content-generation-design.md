# Saat Bazlı Kategori İçerik Üretimi Tasarımı

## Amaç

Devosuit haber sistemi, İstanbul saatine göre belirlenmiş altı yayın diliminde yalnızca o dilimin kategorisini tarayacak ve değerlendirecek. Her dilimde en fazla üç güçlü aday tek Gemini çağrısında puanlanacak; yayınlanabilir en yüksek puanlı aday için özgün bir sosyal medya metni ve yerel olarak oluşturulmuş tek bir Devosuit görseli hazırlanacak.

Bu aşamada X, Instagram ve Threads API'lerine gönderi yapılmayacak. Çıktılar panelde paylaşılmaya hazır biçimde listelenecek.

## Yayın Planı

Saat dilimi `Europe/Istanbul` olacaktır.

| Saat | Kategori |
|---|---|
| 10:00 | Girisim |
| 12:00 | AI |
| 14:00 | Teknoloji |
| 16:00 | AI |
| 18:00 | Yazilim |
| 20:00 | Girisim |

Bir dilimde uygun haber bulunmazsa başka kategoriye geçilmeyecek ve dilim atlanacaktır.

## Mimari

Sistem her yayın dilimini bağımsız ve tekrar çalıştırılabilir bir iş olarak ele alacaktır. Dilim işi yalnızca planlanan kategorinin RSS kaynaklarını toplayacak, yerel ön eleme yapacak, tek bir Gemini isteğiyle adayları değerlendirecek ve kazananın metnini üretecektir. Görsel üretimi Gemini kullanmadan uygulama içinde yapılacaktır.

Eski `scraper.py` ve `publisher.py` hattı bu akışa bağlanmayacaktır. Yeni davranış mevcut `collector.py`, `pipeline.py`, `worker.py`, `gemini_service.py` ve repository tabanlı panel hattında uygulanacaktır.

## Veri Akışı

1. Zamanlayıcı, yayın saatinde ilgili kategoriyle benzersiz bir dilim işi başlatır.
2. Collector yalnızca bu kategorinin RSS adreslerini tarar.
3. Uygulama daha önce kaydedilmiş URL'leri, tekrarları, yaş sınırını aşan haberleri ve içeriği yetersiz kayıtları Gemini çağrısı yapmadan eler.
4. Kalan haberler güncellik ve içerik doluluğu gibi deterministik ölçütlerle sıralanır; en fazla üç aday seçilir.
5. Bulunan 1–3 adayın kısaltılmış kaynak içerikleri tek Gemini isteğine gönderilir.
6. Gemini her aday için 0–10 puan, kısa gerekçe, temel gerçekler, risk işaretleri ve yayınlanabilirlik değeri döndürür.
7. Gemini, yayınlanabilir ve risksiz adaylar arasındaki en yüksek puanlı haberi kazanan olarak işaretler ve yalnız bu haber için özgün Türkçe sosyal medya metni, kısa görsel başlığı ve tek bir görsel vurgu bilgisi üretir.
8. Uygulama seçimi ve cevabı doğrular, bütün adayların puanlarını kaydeder ve kazananı taslak durumuna geçirir.
9. Uygulama 1200×675 boyutunda Devosuit markalı PNG kartı yerel olarak üretir ve haber kaydına bağlar.
10. Panel, hazırlanan kazananı görsel önizlemesi ve metniyle haber listesinin en üstünde gösterir. Detay sayfası tam görsel önizleme ve indirme sunar.

## Gemini İstek Sözleşmesi

Tek istek en fazla üç adayı içerir. Her adayın kimliği, başlığı, kaynağı, yayın zamanı, özeti ve token kullanımını sınırlayan kısaltılmış kaynak metni gönderilir.

Yapılandırılmış cevap şunları içerir:

- Her aday için kimlik, puan, gerekçe, temel gerçekler, riskler ve yayınlanabilirlik.
- Seçilen haber kimliği; güvenli aday yoksa boş değer.
- Yalnız seçilen haber için sosyal medya metni.
- Görsel kartında kullanılacak kısa başlık ve kaynakla doğrulanabilir tek vurgu bilgisi.

Seçilen kimlik, istekte bulunan adaylardan biri olmalıdır. Uygulama, Gemini'nin sıralamasını doğrulayacak; daha düşük puanlı veya riskli bir aday seçilirse güvenli en yüksek puanlı adayı kendisi belirleyecektir.

## Metin Kuralları

Üretilen tek metin X, Instagram ve Threads için ortak paylaşım metnidir. Kaynak bağlantısı daha sonra platform adaptörünce ekleneceği için metne gömülmez.

- Türkçe, doğal ve Devosuit'in profesyonel teknoloji yayın tonunda olacaktır.
- Kaynak başlığını aynen kopyalamayacak ve yalnızca kelimeleri yeniden sıralamayacaktır. Büyük/küçük harf ve noktalama işaretleri yok sayıldıktan sonra metnin ilk cümlesi kaynak başlığıyla aynıysa veya ikisi arasındaki benzerlik oranı yüzde 80'i aşıyorsa cevap reddedilecektir.
- Kaynakta veya doğrulanmış temel gerçeklerde bulunmayan bilgi eklemeyecektir.
- Tıklama tuzağı, doğrulanmamış çıkarım ve kesinlik ifade eden abartı kullanmayacaktır.
- X bağlantı payı korunarak en fazla 240 karakter olacaktır.
- En fazla iki ilgili hashtag içerecektir.
- Boş veya doğrulamadan geçemeyen metin taslak olarak kaydedilmeyecektir.

## Görsel Kuralları

Görsel yapay zekâ ile üretilmeyecektir. Uygulama, seçilen haber için tek bir 1200×675 PNG kart hazırlayacaktır.

Kartta Devosuit renkleri ve logosu, kategori, kısa görsel başlığı, tek vurgu bilgisi, kaynak ve tarih bulunacaktır. Metin taşması, eksik font ve uzun başlıklar deterministik yerleşim kurallarıyla yönetilecektir. Dosya yolu haber kaydında saklanacaktır.

## Tekrarlanabilirlik ve Maliyet Kontrolü

Her iş `tarih + saat + kategori` birleşimiyle benzersiz olacaktır. Aynı dilimin elle veya zamanlayıcı tarafından yeniden tetiklenmesi ikinci bir Gemini çağrısı üretmeyecektir. Başarıyla tamamlanmış dilimler tekrar işlenmeyecek; başarısız dilimler mevcut iş kaydı üzerinden devam edecektir.

Normal çalışma bütçesi, uygun aday bulunan her yayın dilimi için bir Gemini çağrısıdır; bu da günde en fazla altı çağrı demektir. Aday bulunmayan dilimde Gemini çağrısı yapılmaz. Görsel üretimi API veya Gemini tokenı kullanmaz.

## Hata Yönetimi

- `429` yanıtlarında servis tarafından bildirilen yeniden deneme süresi öncelikli olarak kullanılacaktır. Bu değer yoksa sınırlı üstel bekleme uygulanacaktır.
- Kota hataları yeni dilim işlerinin aynı anda Gemini'ye yüklenmesine yol açmayacaktır; tüm Gemini çağrıları mevcut ortak kapıdan seri geçecektir.
- Geçersiz JSON veya doğrulamadan geçmeyen cevap için yalnızca bir otomatik yeniden deneme yapılacaktır. İkinci başarısızlık panelde açıklanabilir hata olarak gösterilecektir.
- Uygun veya güvenli aday yoksa dilim `skipped` olarak tamamlanacak, kategori yedeği kullanılmayacaktır.
- Metin başarılı, görsel başarısız olduğunda metin korunacak ve görsel ayrı olarak yeniden üretilebilecektir.
- Aynı haber daha önce hazırlanmış veya paylaşım için ayrılmışsa başka bir dilimde yeniden seçilmeyecektir.

## Panel Davranışı

Paneldeki yayın planı statik şablon yerine aynı plan tanımından üretilecektir. Her dilim bekliyor, çalışıyor, hazır, atlandı veya hata durumunu gösterecektir.

Hazır içerikler listenin üst bölümünde gösterilecektir. Satır veya kart üzerinde görsel küçük önizlemesi, kategori, puan, yeni metin ve hazırlanan yayın saati bulunacaktır. Haber detayında özgün kaynak metni ile üretilen metin karşılaştırılabilecek; görsel tam boyutta açılabilecek ve indirilebilecektir.

## Test Stratejisi

Testler üretim kodundan önce yazılacaktır ve şu davranışları kapsayacaktır:

- İstanbul saatine göre altı saat-kategori eşleşmesi.
- Bir dilimde yalnızca planlanan kategori kaynaklarının taranması.
- Yerel ön elemenin en fazla üç adayı Gemini'ye taşıması.
- 1–3 adayın tek Gemini çağrısında puanlanması ve yalnız kazanan için metin dönmesi.
- Güvenli en yüksek puanlı adayın seçilmesi; riskli veya yayınlanamaz adayın elenmesi.
- Aynı dilimin yeniden çalıştırılmasının ikinci Gemini çağrısı oluşturmaması.
- Aday olmayan dilimde Gemini çağrısı yapılmadan işin atlanması.
- `429` yeniden deneme süresinin uygulanması ve ortak istek kapısının korunması.
- Geçersiz yapılandırılmış cevapta en fazla bir otomatik tekrar yapılması.
- Başlık kopyası, 240 karakter aşımı, fazla hashtag ve onaysız bilgi içeren metnin reddedilmesi.
- Görselin 1200×675 PNG olarak üretilmesi ve uzun metnin karta taşmaması.
- Hazır görselin panel listesinde ve detay sayfasında görüntülenmesi.
- Hiçbir X, Instagram veya Threads API çağrısının yapılmaması.

## Kapsam Dışı

- X, Instagram ve Threads kimlik doğrulaması ve otomatik paylaşım.
- Yapay zekâ ile fotoğraf veya illüstrasyon üretimi.
- Altı dilim dışındaki saatlerde içerik hazırlama.
- Planlanan kategori boş olduğunda başka kategoriye geçme.
