# SiparişGeldi Pazarlama ve Ürün Özellikleri

## 1. Ürün Tanımı

SiparişGeldi; restoranların ve pazaryeri satıcılarının farklı platformlardan gelen siparişlerini tek panelde takip etmesini, sipariş durumlarını yönetmesini, Telegram ve WhatsApp üzerinden bildirim almasını ve satış kârlılığını analiz etmesini sağlayan çok kanallı sipariş yönetim platformudur.

Temel vaat:

> Sipariş hangi platformdan gelirse gelsin, işletme siparişi tek ekrandan görür, yönetir ve satış performansını ölçer.

## 2. Hedef Kitle

- Birden fazla yemek platformunda satış yapan restoranlar
- Kendi kuryesi ve platform kuryesini birlikte kullanan işletmeler
- Trendyol Go ve Migros Yemek siparişlerini tek ekrandan yönetmek isteyen restoranlar
- Adisyo kullanan kafe ve restoranlar
- Trendyol Pazaryeri ve Hepsiburada üzerinden ürün satan işletmeler
- Sipariş kaçırmak istemeyen işletme sahipleri ve operasyon sorumluları
- Günlük ciro, ürün maliyeti ve gerçek kârını görmek isteyen işletmeler
- Telegram veya WhatsApp üzerinden anlık bildirim almak isteyen ekipler

## 3. Ana Fayda Alanları

### Tek merkezden sipariş yönetimi

- Farklı platformları tek panelde birleştirir.
- Yeni, kabul edilmiş, hazırlanıyor, yolda, teslim edildi ve iptal durumlarını takip etmeyi kolaylaştırır.
- Aktif siparişleri hızlıca görmeyi sağlar.
- Sipariş detayına girmeden aktif siparişler ekranından kabul işlemi yapılabilir.
- Sipariş detayları, müşteri notları ve teslimat bilgileri aynı ekranda tutulur.

### Anlık bildirim

- Yeni sipariş geldiğinde Telegram bildirimi gönderir.
- Pro plan ile WhatsApp bildirimi kullanılabilir.
- Telegram ve WhatsApp birlikte seçilebilir.
- Sipariş durumu değişiklikleri için bildirim alınabilir.
- İptal, iade ve sorunlu durumlar ayrıca bildirilebilir.
- Günlük, haftalık ve aylık rapor bildirimleri desteklenir.
- WhatsApp mesajlarının teslim, okunma ve hata durumları takip edilebilir.

### Operasyon kontrolü

- Sipariş kabul etme
- Siparişi hazırlanıyor/hazırlandı durumuna alma
- Siparişi yola çıktı durumuna alma
- Siparişi teslim edildi/tamamlandı durumuna alma
- Uygun iptal nedeni seçerek siparişi reddetme veya iptal etme
- Restoranı satışa kapatma ve yeniden açma
- Kargo veya teslimat durumunu takip etme
- Sipariş fişi yazdırma

## 4. Platform Entegrasyonları

### Trendyol Go

- Restoran siparişlerini periyodik olarak kontrol eder.
- Yeni siparişleri panelde oluşturur.
- Ürün, adet, fiyat, opsiyon, müşteri notu, teslimat tipi ve ödeme bilgilerini gösterir.
- Telegram ve WhatsApp bildirimleri gönderir.
- Sipariş kabulü ve durum ilerletme aksiyonlarını destekler.
- Paket durumlarını takip eder.
- Restoran çalışma durumunu açma/kapatma aksiyonlarını destekler.
- İptal ve iade bildirimlerini takip eder.
- Sipariş gecikirse ek uyarı üretebilir.
- Market ve yemek servisleri ayrı platform mantığıyla ele alınabilir.

### Migros Yemek

- Webhook tabanlı yeni sipariş alma.
- Sipariş iptal ve teslimat durumu bildirimleri.
- Ürün, adet, fiyat, opsiyon ve alt opsiyon detayları.
- Çıkarılan malzemelerin gösterimi.
- Ürün notu ve sipariş notu.
- Ödeme yöntemi ve toplam tutar.
- Müşteri adı, telefon, adres açıklaması ve adres tarifi.
- Restoran kuryesi veya Migros teslimatı bilgisi.
- Sipariş kabulü.
- Hazırlandı, yola çıktı ve tamamlandı akışları.
- Sipariş reddetme ve iptal nedeni seçme.
- Restoranı satışa kapatma/açma.
- Fiş yazdırma.
- Telegram ve WhatsApp bildirimleri.

Canlı ortam bilgisi Migros tarafından onaylanmıştır. Canlı kullanım için Migros Restoran Paneli üzerinden SiparişGeldi seçilerek restoran API Key oluşturulması gerekir.

### Adisyo

- Restoran satışlarını Adisyo API üzerinden okur.
- Günlük rapor oluşturur.
- Sipariş sayısını gösterir.
- İptal sayılarını gösterir.
- Brüt ve geçerli ciroyu gösterir.
- Satılan ürünleri adet ve tutar bazında listeler.
- Ödeme yöntemlerini özetler.
- Günlük raporu Telegram ve WhatsApp üzerinden gönderebilir.
- Maliyet ve kârlılık ekranında Adisyo ürünlerini diğer platformlarla birlikte hesaplar.

Adisyo entegrasyonu sipariş operasyonu için değil, satış ve raporlama odaklıdır. Adisyo’dan gelen satışların hazır günlük rapor olarak işlenmesi gerekir.

### Trendyol Pazaryeri

- Siparişleri API üzerinden çeker.
- Sipariş ürünlerini ve tutarlarını gösterir.
- Yeni sipariş bildirimleri gönderir.
- Sipariş ve paket durumlarını takip eder.
- Satış, komisyon, ürün maliyeti ve kârlılık analizine dahil eder.

### Hepsiburada

- Merchant ID, kullanıcı ve servis anahtarıyla bağlantı kurulabilir.
- Test ve canlı ortam ayrımı bulunur.
- Sipariş ve paket bilgileri takip edilir.
- Ürün, adet, tutar ve kargo durumları panelde gösterilebilir.

### Yemeksepeti

- Partner API ve webhook mimarisi için altyapı hazırlanmıştır.
- Sipariş webhook’u üzerinden sipariş alma hedeflenir.
- OAuth 2.0 kimlik doğrulama yapısı desteklenir.
- Sipariş, ürün, opsiyon, ödeme, adres ve müşteri detayları için veri modeli hazırlanmıştır.
- Canlı kullanım için Yemeksepeti’nden partner yetkilendirmesi ve mağaza bilgileri gerekir.

### Getir Yemek

Backend tarafında önceki entegrasyon altyapısı korunmaktadır; ancak kullanıcı panelinde aktif platform olarak sunulmamaktadır. Pazarlama iletişiminde aktif ve doğrulanmış entegrasyon olarak belirtilmemelidir.

## 5. Sipariş Detayları

Platformun desteklediği payload yapısına göre sipariş ekranında şu alanlar gösterilebilir:

- Sipariş numarası
- Sipariş tarihi ve saati
- Sipariş durumu
- Ürün adı
- Ürün adedi
- Birim fiyat
- Satır toplamı
- Opsiyonlar
- Alt opsiyonlar
- Çıkarılan malzemeler
- Opsiyon adedi ve fiyatı
- Ürün notu
- Sipariş notu
- Ödeme yöntemi
- Ara toplam
- İndirim
- Toplam tutar
- Müşteri adı
- Müşteri telefonu
- Teslimat adresi
- Adres tarifi
- Teslimat yöntemi
- Kurye bilgisi
- Restoran tercihleri

## 6. Bildirim Kanalları

### Telegram

- Ücretsiz planda temel bildirim kanalıdır.
- Bot bağlantısı ile çalışır.
- Yeni sipariş bildirimi.
- Durum değişikliği bildirimi.
- İptal/iade bildirimi.
- Günlük, haftalık ve aylık raporlar.

### WhatsApp

- Pro plan özelliğidir.
- Meta WhatsApp Cloud API kullanılır.
- Onaylı WhatsApp şablonlarıyla çalışır.
- Yeni sipariş ve rapor bildirimleri gönderilebilir.
- Telegram ile birlikte kullanılabilir.
- Gönderim durumu panelden izlenebilir.

WhatsApp’ta proaktif mesaj göndermek için Meta tarafından onaylanmış şablonlar gerekir. Şablon onayı, mesaj teslimi ve Meta hesap durumu platform dışı bağımlılıklardır.

## 7. İstatistik ve Raporlama

- Günlük sipariş sayısı.
- Haftalık sipariş sayısı.
- Aylık sipariş sayısı.
- Platform bazında sipariş dağılımı.
- Saatlik yoğunluk analizi.
- Günlere göre karşılaştırma.
- Bu hafta/geçen hafta karşılaştırması.
- Önceki haftanın aynı günüyle kıyaslama.
- Günlük ciro.
- Platform bazında ciro.
- Satılan ürün adedi.
- En çok satan ürünler.
- Adisyo ödeme yöntemi özeti.
- Telegram ve WhatsApp rapor gönderimi.

## 8. Maliyet ve Kârlılık

Maliyet ekranı siparişlerden veya Adisyo günlük raporlarından gelen ürünleri otomatik listeler.

Kullanıcı:

- Ürünün tek birim maliyetini girer.
- Aynı ürünün farklı platformlardaki satış fiyatlarını ayrı görür.
- Platform filtresi kullanır.
- Ürün adına göre arama yapar.
- Son 7, 30, 90 gün veya 1 yıl seçer.
- Başlangıç ve bitiş tarihini kendisi belirler.
- Platform komisyon oranı girer.
- Sipariş başı paket/ekstra gider tanımlar.
- Dönem toplamı sabit gider tanımlar.

Kâr hesabı:

```text
Toplam ciro
- Platform komisyonu
- Ürün maliyeti
- Paketleme ve diğer giderler
= Tahmini kâr
```

Günlük görünümde:

- Tarih
- Sipariş sayısı
- Ciro
- Ürün maliyeti
- Komisyon
- Diğer gider
- Tahmini kâr
- Kâr marjı

Her güne tıklanarak o gün satılan ürünler, adetleri, satış toplamı, maliyet ve ürün bazlı kâr görüntülenebilir.

Bu hesaplama muhasebe veya vergi beyannamesi yerine operasyonel kârlılık tahmini olarak konumlandırılmalıdır.

## 9. Abonelik ve Pro Plan

### Ücretsiz plan

- Telegram bildirimi.
- Sınırlı platform kullanımı.
- Sipariş paneli.
- Temel rapor ekranları.

### Pro plan

- WhatsApp bildirimi.
- Telegram + WhatsApp birlikte kullanım.
- Çoklu platform bağlantısı.
- Sipariş ve durum bildirimleri.
- Genişletilmiş raporlar.
- Maliyet ve kârlılık özellikleri.

### Ödeme

- PayTR iFrame API kullanılır.
- Kart bilgileri SiparişGeldi sunucusunda tutulmaz.
- Test ödeme modu bulunur.
- Başarılı ödeme PayTR callback’i ile doğrulanır.
- Başarılı ödeme sonrası Pro erişimi 30 gün açılır.
- Abonelik ekranında kalan gün ve bitiş tarihi gösterilir.
- Sürenin son 5 gününde panel uyarısı gösterilebilir.
- Admin tarafından kullanıcıya ek Pro günü tanımlanabilir.

Not: Otomatik aylık kart yenilemesi ayrıca PayTR recurring/subscription yetkisine bağlıdır. Bu özellik onaylanmadan otomatik yenileme vaat edilmemelidir.

## 10. Yönetici Özellikleri

- Kullanıcıları listeleme.
- Kullanıcı arama ve kanal filtreleme.
- Kullanıcının planını Pro/Ücretsiz olarak değiştirme.
- WhatsApp ve çoklu platform yetkilerini yönetme.
- Telegram, WhatsApp veya her iki bildirim kanalını seçme.
- Kullanıcının Pro kalan gününü görme.
- Kullanıcıya gün bazında ek Pro süresi tanımlama.
- Bağlı platformları görme.
- Sipariş sayılarını görme.
- Entegrasyon hatalarını takip etme.
- Test bildirimi gönderme.

## 11. Güvenlik ve Teknik Altyapı

- Flask tabanlı web uygulaması.
- PostgreSQL destekli üretim veritabanı.
- Railway üzerinde çalıştırılabilir.
- API anahtarları ortam değişkenlerinde tutulur.
- Kullanıcı platform anahtarları şifreli saklanır.
- Webhook uç noktalarında doğrulama bulunur.
- Migros Basic Auth desteği.
- WhatsApp webhook imza doğrulaması.
- Yemeksepeti webhook token doğrulaması.
- Trendyol marketplace webhook anahtarı.
- PayTR callback hash doğrulaması.
- Tekrarlanan callback ve bildirimlerde idempotency kontrolleri.
- CSRF koruması.
- Güvenli oturum çerezleri.
- Platform erişim yetkisi ve plan kontrolü.

## 12. Pazarlama Mesajları

### Kısa slogan seçenekleri

- Tüm siparişlerin tek ekranda.
- Siparişi kaçırma, kârını gör.
- Restoran operasyonunun tek merkezi.
- Platformlar çoğalsın, kontrol sende kalsın.
- Siparişten kâra, tüm işletme görünürlüğü tek panelde.

### Kısa ürün açıklaması

SiparişGeldi; Trendyol Go, Migros Yemek, Adisyo ve diğer satış kanallarınızı tek panelde birleştirir. Yeni siparişleri anında Telegram veya WhatsApp’tan alın, sipariş durumlarını yönetin, günlük cironuzu ve gerçek maliyetlerinizi takip ederek tahmini kârınızı görün.

### Restoran sahibine anlatım

“Farklı uygulamalardan gelen siparişleri ayrı ayrı kontrol etmek yerine SiparişGeldi ile tek panelden yönetirsiniz. Sipariş geldiğinde telefonunuza bildirim gelir, siparişi kabul eder ve durumunu ilerletirsiniz. Gün sonunda hangi platformdan ne kadar satış yaptığınızı, komisyon ve ürün maliyetlerinden sonra yaklaşık ne kadar kazandığınızı görürsünüz.”

### Pro plan satış metni

“WhatsApp bildirimleri, çoklu platform bağlantısı, gelişmiş sipariş takibi ve maliyet/kârlılık raporlarıyla operasyonunuzu büyütün. SiparişGeldi Pro ile siparişlerinizi kaçırmadan yönetin, satış kanallarınızın gerçek katkısını ölçün.”

## 13. Demo Akışı

1. Kullanıcı panele giriş yapar.
2. Bir veya daha fazla platform bağlantısını ekler.
3. Test bağlantısını doğrular.
4. Yeni sipariş panelde gösterilir.
5. Telegram/WhatsApp bildirimi alınır.
6. Sipariş kabul edilir ve durum ilerletilir.
7. Sipariş detayındaki ürün ve opsiyonlar incelenir.
8. Fiş yazdırılır.
9. Günlük istatistik ekranı açılır.
10. Maliyet ekranında ürün maliyeti ve komisyon girilir.
11. Günlük ciro ve tahmini kâr gösterilir.

## 14. Pazarlama Öncesi Kontrol Listesi

- [ ] Her platform için canlı/test durumu netleştirildi.
- [ ] Migros canlı geçişi tamamlandı ve restoran API Key’i alındı.
- [ ] WhatsApp Meta şablonları onaylandı.
- [ ] PayTR test işlemi ve callback doğrulandı.
- [ ] PayTR canlı mod şartları tamamlandı.
- [ ] Gizlilik, mesafeli satış, ön bilgilendirme ve iade metinleri yayında.
- [ ] Fiyatlandırma ve Pro kapsamı netleştirildi.
- [ ] Otomatik yenileme desteklenmiyorsa açıkça belirtildi.
- [ ] Yemeksepeti yetkilendirme durumu netleştirildi.
- [ ] Her entegrasyon için örnek demo hesabı veya test akışı hazırlandı.
- [ ] Destek ve iletişim kanalı belirlendi.
- [ ] API anahtarları ve gizli bilgiler tanıtım materyallerine konulmadı.

## 15. Doğru Konumlandırma

SiparişGeldi’yi yalnızca “bildirim gönderen bir uygulama” olarak değil, şu üç katmanı birleştiren işletme aracı olarak konumlandırmak daha doğrudur:

1. **Operasyon:** Siparişi gör, kabul et, hazırla, teslimata çıkar.
2. **İletişim:** Sipariş ve durum bildirimlerini Telegram/WhatsApp’tan al.
3. **Finansal görünürlük:** Ciro, komisyon, maliyet ve tahmini kârı takip et.

Bu üç katman, ürünü basit bir entegrasyon aracından restoranın günlük karar destek paneline dönüştürür.
