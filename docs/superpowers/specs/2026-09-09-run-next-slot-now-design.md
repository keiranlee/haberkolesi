# Sıradaki Dilimi Şimdi Çalıştırma Tasarımı

## Amaç

Editör, plan saatini beklemeden panelden sıradaki yayın diliminin kategorisini test edebilmelidir. İşlem yalnız o kategorinin güncel RSS kaynaklarını tarar, en fazla üç uygun adayı tek Gemini çağrısında değerlendirir ve kazanan için metin ile görsel hazırlar.

## Davranış

- İstanbul saatindeki ilk gelecek yayın dilimi seçilir. Günün son diliminden sonra ertesi günün 10:00 Girişim dilimi seçilir.
- Panel, seçilecek saati ve kategoriyi düğme üzerinde gösterir.
- POST isteği yönetici oturumu ve CSRF doğrulaması gerektirir.
- İşlem arka planda çalışır; panel mevcut canlı yenileme mekanizmasıyla sonucu gösterir.
- Her manuel test benzersiz `test:` anahtarıyla `content_runs` tablosuna kaydedilir. Bu anahtar gerçek planlı dilimin anahtarıyla çakışmaz ve planlı çalışmayı tüketmez.
- Her tıklama yeni RSS taraması ve bir Gemini batch çağrısı başlatabilir. Düğme bu maliyeti açıkça belirtir.
- Eşzamanlı ikinci manuel test, uygulama seviyesindeki kilitle engellenir.
- X, Instagram veya Threads paylaşımı yapılmaz.

## Bileşenler

- `schedule.py`: Verilen zamandan sonraki ilk `PublishingSlot` değerini hesaplar.
- `scheduled_content.py`: Test çalışması için ayrı anahtar üretir ve mevcut güvenli içerik hazırlama akışını yeniden kullanır.
- `app.py` ve `main.py`: Runner'ı uygulamaya geçirir, korumalı manuel test route'unu ekler ve arka plan görevini başlatır.
- `templates/dashboard.html` ve `static/dashboard.js`: Sıradaki kategori düğmesini ve çalışma durumunu sunar.

## Hata Davranışı

Runner mevcut davranışı korur: aday bulunamazsa veya puan eşik altındaysa test `skipped`, servis hatasında `failed`, içerik hazırlandığında `ready` olur. Hata gerçek planlı dilimi etkilemez.

## Doğrulama

- Gece, dilimler arası ve 20:00 sonrası sıradaki dilim hesabı test edilir.
- Manuel ve planlı anahtarların ayrılığı test edilir.
- Route için oturum, CSRF, arka plan çağrısı ve panel metni test edilir.
- Tüm test paketi, Python derleme kontrolü, diff kontrolü ve yerel sağlık kontrolü çalıştırılır.
