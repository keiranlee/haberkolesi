# RSS Canlı Toplama Testi

**Tarih:** 24 Ağustos 2026  
**Kapsam:** `config.py` içindeki 17 RSS adresinin her birinden en güncel ilk girdinin salt-okunur olarak alınması. Bu test Gemini puanlama/çeviri, PostgreSQL kaydı, X toplama ve sosyal medya paylaşımını çalıştırmaz.

## Özet

- 17 RSS kaynağının **12'sinden** güncel örnek haber alındı.
- **5 kaynakta** erişim veya XML ayrıştırma sorunu gözlendi.
- Erişilebilen örnekler; girişim yatırımı ve AI araçları, tüketici teknolojisi, yapay zekâ davaları, GPU/yazılım geliştirmeleri ve Java sürümleri gibi konulara dağılıyor.

## Çekilen haber örnekleri

| Kategori | Kaynak | Başlık | Tarih | Kısa özet |
|---|---|---|---|---|
| Startup | eGirişim | [Hangi girişimler yatırım alıyor? Yatırımcılar bir girişimde neye bakıyor?](https://egirisim.com/2026/08/24/hangi-girisimler-yatirim-aliyor-yatirimcilar-bir-girisimde-neye-bakiyor-basak-zorlutuna-e2vc/) | 24 Ağu 2026 | e2vc'den Başak Zorlutuna ile yatırım yaklaşımı, yatırım kararları ve kurucu-yatırımcı ilişkisi üzerine söyleşi. |
| Startup | Foundern | [Istanbul Ignited by Slush’D 12–14 Ekim’de Geri Dönüyor!](https://foundern.com/2026/08/slushd-12-14-ekimde-geri-donuyor/) | 20 Ağu 2026 | Akbank ve Togg sponsorluğundaki etkinlik; OpenAI ve NVIDIA dahil teknoloji şirketlerini İstanbul'da buluşturmayı hedefliyor. |
| Startup | Entrepreneur | [7 New AI Tools That Run a One-Person Business in 2026](https://www.entrepreneur.com/business-news/7-new-ai-tools-that-run-a-one-person-business-in-2026-no-staff-no-code) | 22 Ağu 2026 | Personelsiz ve kod yazmadan tek kişilik işletme yürütmeye odaklanan yedi AI aracı. |
| Startup | Forbes | [The Complex Psychology Of People Choosing To Trust Either Humans Or AI](https://www.forbes.com/sites/lanceeliot/2026/08/24/the-complex-psychology-of-people-choosing-to-trust-either-humans-or-ai/) | 24 Ağu 2026 | İnsanların insanlara veya AI'a güvenme tercihinin psikolojisi. |
| Teknoloji | DonanımHaber | [iPhone Ultra test kullanıcılarının beğenisini kazandı](https://www.donanimhaber.com/iphone-ultra-test-kullanicilarinin-begenisini-kazandi--209657) | 24 Ağu 2026 | Apple'ın ilk katlanabilir telefonu olduğu iddia edilen iPhone Ultra'nın test kullanıcılarındaki ilk izlenimleri. |
| Teknoloji | ShiftDelete | [Yayıncı İçeriklerini İzinsiz Kullanmışlar: Twitch’e Yapay Zeka Davası](https://shiftdelete.net/twitch-amazon-yapay-zeka-davasi) | 24 Ağu 2026 | Twitch ve Amazon'a, yayıncı içeriklerini AI eğitimi için izinsiz kullanma iddiasıyla açılan toplu dava. |
| Teknoloji | Technopat | [DLSS 4.5 Ray Reconstruction erkenden kullanıma açıldı](https://www.technopat.net/2026/08/24/dlss-4-5-ray-reconstruction-erkenden-kullanima-acildi/) | 24 Ağu 2026 | NVIDIA DLSS 4.5 Ray Reconstruction dosyalarının DLSS Swapper üzerinden erken kullanımı. |
| Teknoloji | The Verge | [GTA 6 news, trailers, and everything we know](https://www.theverge.com/23987993/gta-6-news-trailers-rockstar-games) | 23 Ağu 2026 | GTA VI'nın geliştirme süreci, gecikmeleri ve açıklanan çıkış tarihi özeti. |
| Teknoloji | TechCrunch | [Who’s behind the new ‘stealth model’ Ox Alpha?](https://techcrunch.com/2026/08/23/whos-behind-the-new-stealth-model-ox-alpha/) | 23 Ağu 2026 | Ox Alpha adlı gizemli yeni AI modeli hakkındaki tartışmalar. |
| Yazilim | CHIP | [MIT araştırmacıları canlı bakterilerle biyolojik transistör geliştirdi](https://www.chip.com.tr/guncel/mit-arastirmacilari-canli-bakterilerle-biyolojik-transistor-gelistirdi_183053.html) | 24 Ağu 2026 | Canlı bakteriler kullanılarak geliştirilen biyolojik transistör çalışması. |
| Yazilim | InfoQ | [JDK 27 and JDK 28: What We Know So Far](https://www.infoq.com/news/2026/08/java-27-so-far/?utm_campaign=infoq_content&utm_source=infoq&utm_medium=feed&utm_term=global) | 24 Ağu 2026 | JDK 27'nin dokuz yeni özelliği ve JDK 28 için olası hedefler. |
| Yazilim | Hacker News | [Everything I own, owned](https://schlarp.com/posts/everything-i-own-owned/) | 23 Ağu 2026 | Kişisel dijital sahiplik üzerine Hacker News'te paylaşılan yazı. |

## Erişim/parsing sorunu görülen kaynaklar

| Kategori | Kaynak | Test sonucu |
|---|---|---|
| Startup | Swipeline | RSS XML'i kapatılmamış CDATA bölümü nedeniyle ayrıştırılamadı. |
| AI | The Rundown | Kalıcı yönlendirme (`308`) döndü. |
| AI | AI News | `403 Forbidden` döndü. |
| AI | VentureBeat | Kalıcı yönlendirme (`308`) döndü. |
| AI | MarkTechPost | `403 Forbidden` döndü. |

## Notlar

- Uygulamanın gerçek toplayıcısı `feedparser` kullanır; bu test ortamında o paket kurulu olmadığı için standart XML ayrıştırıcıyla kontrol yapıldı. `feedparser`, hatalı RSS ve yönlendirme senaryolarında farklı sonuç verebilir.
- Gerçek akışta içerik sayfaları `trafilatura` ile çekilir, İngilizce içerikler Türkçeye çevrilir ve Gemini yalnızca eşiği geçen haberleri kaydeder. Bu rapordaki girdiler henüz bu filtrelerden geçmediği için botun nihai paylaşım havuzu değildir.
