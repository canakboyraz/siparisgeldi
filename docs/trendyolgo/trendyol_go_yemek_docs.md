# Trendyol Go Yemek Entegrasyonu Yerel Arsiv

Kaynak kategori: https://developers.tgoapps.com/docs/category/8-uber-eats-trendyol-go---yemek-entegrasyonu

Not: Bu dosya Docusaurus JS bundle icinden cikarilmis yerel calisma arsividir. Gizli bilgi icermez.

## 8.trendyol-go-yemek-entegrasyonu/iade-entegrasyonu/1.ymk-iade-siparisleri-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/dc463f0a.103d1f32.js`
- Module: `9573`

### Cikarilan metin / endpoint ipuclari

- de\u011feri (packageId), 64 karakter uzunlu\u011funda alfanumerik bir de\u011ferdir. Sipari\u015f ak\u0131\u015flar\u0131n\u0131z\u0131n etkilenmemesi i\xe7in sisteminizi buna uygun hale getirmeniz \xf6nemlidir.')),(0,r.kt)(
- değeri, tam iadeyi temsil ederken,
- de\u011feri kadar iade a\xe7\u0131ld\u0131\u011f\u0131n\u0131 temsil etmektedir.')),(0,r.kt)(
- alan\u0131, o item i\xe7in iade tutar\u0131n\u0131 g\xf6stermektedir. Ayn\u0131 item i\xe7in \xf6nce
- },'Sat\u0131c\u0131ya yap\u0131lan iade t\xfcr\xfc ile ilgili entegrasyon modeline
- alanı eklenmiştir. Para iadesi olacak ise ilgili alan ',(0,r.kt)(
- Claim item status bilgisi Accepted veya Rejected oldu\u011funda iadenin kabul edilme ya da reddedilme tarihi completionDate alan\u0131ndan d\xf6n\xfclecektir. WaitingInAction ve Unresolved stat\xfclerinde ise completionDate bilgisi null d\xf6nmektedir.
- GET
- https://api.tgoapis.com/integrator/claim/meal/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/claim/meal/suppliers/
- storeId
- itemStatuses
- Status
- Kabul edilen iadelerin stat\xfcleri Accepted olur.
- Reddedilen iade paketleri Rejected stat\xfcs\xfcnde olur.
- Para iadesi yapılacak ise;
- packageId
- status
- SKT - Ge\xe7mi\u015f \xdcr\xfcn Teslimat\u0131
- Sat\u0131c\u0131 para iade/\xfcr\xfcn telafisi yapt\u0131
- SKT - Yakla\u015fm\u0131\u015f \xdcr\xfcn Teslimat\u0131
- Teslim alınmamış sipariş - Model 2
- Teslim alınmamış sipariş - Model1
- Teslimat s\u0131ras\u0131nda farkedilen yanl\u0131\u015f/d\xfc\u015f\xfck kalitede \xfcr\xfcn

## 8.trendyol-go-yemek-entegrasyonu/iade-entegrasyonu/2.ymk-iade-onaylama-reddetme.md

- Chunk: `https://developers.tgoapps.com/assets/js/ee3739c4.5517d5f1.js`
- Module: `7517`

### Cikarilan metin / endpoint ipuclari

- İade Siparişlerini Onaylama - PUT claimAccept
- https://api.tgoapis.com/integrator/claim/meal/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/claim/meal/suppliers/
- İade Siparişlerini Reddetme - PUT claimUnresolve
- 5016 - Fi\u015f m\xfc\u015fteriye yeniden g\xf6nderildi, iade yap\u0131lmayacak

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/1.ymk-menulerin-alinmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/bf75b7bb.8822f532.js`
- Module: `8818`

### Cikarilan metin / endpoint ipuclari

- GET getRestaurantProducts
- https://api.tgoapis.com/integrator/product/meal/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/product/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait men\xfcleri response'da bulabilirsiniz.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/2.ymk-kategori-satisa-acma-kapama.md

- Chunk: `https://developers.tgoapps.com/assets/js/e650076e.5c4e25fb.js`
- Module: `9240`

### Cikarilan metin / endpoint ipuclari

- PUT updateRestaurantSectionStatus
- https://api.tgoapis.com/integrator/product/meal/suppliers/
- supplierId
- /stores/
- storeId
- /status
- https://stageapi.tgoapis.com/integrator/product/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/3.ymk-urunleri-satisa-acma-kapama.md

- Chunk: `https://developers.tgoapps.com/assets/js/f9544942.6f71fe48.js`
- Module: `8272`

### Cikarilan metin / endpoint ipuclari

- PUT updateRestaurantProductStatus
- https://api.tgoapis.com/integrator/product/meal/suppliers/
- supplierId
- /stores/
- storeId
- /status
- https://stageapi.tgoapis.com/integrator/product/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/4.ymk-urun-fiyat-guncelleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/6bb6f31f.6ded44a8.js`
- Module: `8375`

### Cikarilan metin / endpoint ipuclari

- - RestoranId Değerleri:
- Restoran isimlerine ait
- POST updatePrice
- https://api.tgoapis.com/integrator/product/meal/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/product/meal/suppliers/
- Status Code
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/5.ymk-toplu-islem-kontrolu.md

- Chunk: `https://developers.tgoapps.com/assets/js/9d6189f8.a9fa6b84.js`
- Module: `3609`

### Cikarilan metin / endpoint ipuclari

- GET getBatchRequestResult (BatchRequest Sonucu)​
- https://api.tgoapis.com/integrator/product/meal/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/product/meal/suppliers/
- status
- API
- Status Code
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/menu-entegrasyonu/6.ymk-hata-kodlari-ve-sorun-giderme.md

- Chunk: `https://developers.tgoapps.com/assets/js/758e04c3.22cba5f1.js`
- Module: `5723`

### Cikarilan metin / endpoint ipuclari

- HTTP Status Kodları
- Status Code
- supplierID, API Key veya API Secret Key bilgilerinden biri eksik ya da yanl\u0131\u015f. Ayr\u0131ca, farkl\u0131 bir sat\u0131c\u0131ya ait restorana eri\u015fmeye \xe7al\u0131\u015f\u0131yorsan\u0131z da bu hata d\xf6n\xfcl\xfcr.
- Endpoint i\xe7in yanl\u0131\u015f HTTP metodu kullan\u0131lm\u0131\u015f.
- Enum tipli bir alana ge\xe7ersiz de\u011fer g\xf6nderilmi\u015f (\xf6rne\u011fin status alan\u0131na ACTIVE/PASSIVE d\u0131\u015f\u0131nda bir de\u011fer).
- API Key / Secret Key hatalı, supplierId size ait değil veya restaurantId belirtilen supplier'a ait değil.

## 8.trendyol-go-yemek-entegrasyonu/restoran-degerlendirme-entegrasyonu/1.ymk-restoran-scorelar\u0131n\u0131-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/572c6a62.ebe9586b.js`
- Module: `6834`

### Cikarilan metin / endpoint ipuclari

- Restoran Genel De\u011ferlendirmelerini \xc7ekme Servisi
- Method GET
- https://api.tgoapis.com/integrator/review/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/review/meal/suppliers/

## 8.trendyol-go-yemek-entegrasyonu/restoran-degerlendirme-entegrasyonu/2.ymk-restoran-yorumlari-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/677329ec.f92b4ffe.js`
- Module: `1609`

### Cikarilan metin / endpoint ipuclari

- Restoran De\u011ferlendirme ve Yorumlar\u0131n\u0131 \xc7ekme Servisi
- Restoran\u0131n yan\u0131t\u0131 reddildi\u011fi durumda rejectedReason i\xe7erisinde red nedeni ve id bilgisi d\xf6n\xfclmektedir.
- Method GET
- https://api.tgoapis.com/integrator/review/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/review/meal/suppliers/
- restaurantAnswerStatus
- \xd6rnek Servis Cevab\u0131 (restaurantAnswerStatus=APPROVED)
- status
- \xd6rnek Servis Cevab\u0131 (restaurantAnswerStatus=REJECTED)

## 8.trendyol-go-yemek-entegrasyonu/restoran-degerlendirme-entegrasyonu/3.ymk-restoran-cevap-verme.md

- Chunk: `https://developers.tgoapps.com/assets/js/6bb36ecd.df37fbda.js`
- Module: `6457`

### Cikarilan metin / endpoint ipuclari

- Restoranlar\u0131n M\xfc\u015fteri Yorumlar\u0131na Cevap Verme Servisi
- Method POST
- https://api.tgoapis.com/integrator/review/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/review/meal/suppliers/
- supplierId

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/1.ymk-restoranlarin-bilgilerinin-alinmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/3a628b53.d7e34f0e.js`
- Module: `2271`

### Cikarilan metin / endpoint ipuclari

- Restoranların Bilgilerinin Alınması
- GET getRestaurants
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- Restoran
- supplierId
- workingStatus
- averageOrderPreparationTimeInMin
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/2.ymk-teslimat-bolgelerinin-alinmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/bffe530a.29bca31d.js`
- Module: `1332`

### Cikarilan metin / endpoint ipuclari

- Teslimat B\xf6lgeleri Bilgisinin Al\u0131nmas\u0131
- Restoran\u0131n Teslimat B\xf6lgeleri Bilgisinin Al\u0131nmas\u0131
- GET getRestaurantDeliveryAreas
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/3.ymk-teslimat-bolgeleri-guncellemesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/8c8f7b5b.43b7e37e.js`
- Module: `2050`

### Cikarilan metin / endpoint ipuclari

- Teslimat B\xf6lgeleri G\xfcncellenmesi
- Restoran\u0131n Teslimat B\xf6lgeleri G\xfcncellenmesi
- PUT updateRestaurantDeliveryAreas
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/4.ymk-restoranin-calisma-saatlerinin-guncellenmesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/97773b82.c90ad1ee.js`
- Module: `666`

### Cikarilan metin / endpoint ipuclari

- Restoran\u0131n \xc7al\u0131\u015fma Saatlerinin G\xfcncellemesi
- PUT updateRestaurantWorkingHours
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/5.ymk-restoranin-calisma-durumu-guncellemesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/8eaf8688.e02f9405.js`
- Module: `6364`

### Cikarilan metin / endpoint ipuclari

- Restoran\u0131n \xc7al\u0131\u015fma Durumunu G\xfcncellemesi
- PUT updateRestaurantWorkingStatus
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores/
- storeId
- /status
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/restoran-entegrasyonu/6.ymk-teslimat-suresi-guncelleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/b7e49e33.991add02.js`
- Module: `154`

### Cikarilan metin / endpoint ipuclari

- Teslimat S\xfcresi G\xfcncelleme
- Teslimat s\xfcrelerini g\xfcncellemek i\xe7in g\xf6nderilecek olan Max ve Min alanlar\u0131 bo\u015f b\u0131rak\u0131lamaz.
- PUT updateRestaurantDeliveryTime
- https://api.tgoapis.com/integrator/store/meal/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/meal/suppliers/
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/1.ymk-paket-modelleri.md

- Chunk: `https://developers.tgoapps.com/assets/js/8719cb98.b7c718c0.js`
- Module: `2670`

### Cikarilan metin / endpoint ipuclari

- Paket Modelleri
- Paket Stat\xfcleri
- Teslim edilen siparişlerdir.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/10.ymk-fatura-silme.md

- Chunk: `https://developers.tgoapps.com/assets/js/631ed50f.a1c3adf4.js`
- Module: `431`

### Cikarilan metin / endpoint ipuclari

- METHOD: POST
- https://api.tgoapis.com/integrator/invoice/meal/suppliers/
- supplierId
- /supplier-invoice-links/delete

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/2.ymk-test-siparisi-olusturma.md

- Chunk: `https://developers.tgoapps.com/assets/js/348913aa.fb9af39e.js`
- Module: `7922`

### Cikarilan metin / endpoint ipuclari

- POST
- https://stageapi.tgoapis.com/integrator/meal-test-order/orders/meal
- store
- storeId
- supplierId
- mealCardType
- , // E\u011fer isPaidWithMealCard alan\u0131 true ise mealCardType alan\u0131 i\xe7in mealCardName (PLUXEE, MULTINET,EDENRED gibi) yaz\u0131l\u0131r.
- isGalaxyOrder

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/3.ymk-siparis-paketlerini.cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/9dd676c8.82dced9e.js`
- Module: `7762`

### Cikarilan metin / endpoint ipuclari

- Sipari\u015f Paketlerini \xc7ekme
- değeri (packageId), 64 karakter uzunluğunda alfanumerik bir değerdir. Bu kimlik, sipariş paketini benzersiz bir şekilde tanımlar.')),(0,r.kt)(
- Model 2 (Uber Eats Trendyol Go Kuryesi ile Teslimat):
- mealCard
- packageStatuses=Cancelled,Picking
- Teslimat \xdccreti
- GET
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- GET packageId
- /packages/
- packageId
- supplierId
- storeId
- packageStatuses
- Paket stat\xfcs\xfc (Created, Picking, Invoiced, Cancelled, UnSupplied, Shipped, Delivered)
- packageModificationStartDate
- Paket g\xfcncelleme ba\u015flang\u0131\xe7 zaman\u0131 (Epoch timestamp milliseconds)
- packageModificationEndDate
- Paket g\xfcncelleme biti\u015f zaman\u0131 (Epoch timestamp milliseconds)
- storePickupSelected
- packageCreationDate
- packageModificationDate
- packageStatus
- packageItemId
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Dış sistem {packageId} kaynağı bulunamadı. Neden: DomainNotFound.
- Belirtilen packageId ile herhangi bir paket bulunmadığında bu hata ile karşılaşırsınız.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/4.ymk-siparisi-kabul-etme.md

- Chunk: `https://developers.tgoapps.com/assets/js/9da82f45.04575b35.js`
- Module: `7747`

### Cikarilan metin / endpoint ipuclari

- PUT
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages/picked
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- packageId
- Paket id'si
- Paketi haz\u0131rlama s\xfcresi
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Değişiklik yapmak istediğiniz paket, kullandığınız supplierID ile ilişkili değildir.
- Dış sistem {packageId} kaynağı bulunamadı. Neden: DomainNotFound.
- Belirtilen packageId ile herhangi bir paket bulunmadığında bu hata ile karşılaşırsınız.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/5.ymk-siparis-hazirliginin-bitmesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/e2c29b28.21f8f833.js`
- Module: `5528`

### Cikarilan metin / endpoint ipuclari

- PUT
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages/invoiced
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- packageId
- Paket id'si
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Değişiklik yapmak istediğiniz paket, kullandığınız supplierID ile ilişkili değildir.
- Teslim edilmi\u015f bir sipari\u015fi iptal etmeye \xe7al\u0131\u015f\u0131rken veya iptal olan bir sipari\u015fi teslim etmeye \xe7al\u0131\u015f\u0131rken bu hata d\xf6nmektedir.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/6.ymk-siparisin-yola-cikmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/508c62fc.6d2c7ee1.js`
- Module: `5592`

### Cikarilan metin / endpoint ipuclari

- PUT
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- Paket id'si
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Değişiklik yapmak istediğiniz paket, kullandığınız supplierID ile ilişkili değildir.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/7.ymk-siparisin-teslim-edilmesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/b31ad4bf.81887df7.js`
- Module: `7039`

### Cikarilan metin / endpoint ipuclari

- Siparişin Teslim Edilmesi
- PUT
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- Paket id'si
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Değişiklik yapmak istediğiniz paket, kullandığınız supplierID ile ilişkili değildir.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/8.ymk-siparis-iptali.md

- Chunk: `https://developers.tgoapps.com/assets/js/857eba6f.bf847a10.js`
- Module: `6795`

### Cikarilan metin / endpoint ipuclari

- Sipari\u015f Paketlerini \xc7ekme Servisi
- \xfczerinden d\xf6n\xfclen packageItemId bilgilerinin hepsi itemIdList i\xe7erisinde kullan\u0131lmal\u0131d\u0131r.
- yap\u0131lmak istenirse hangi \xfcr\xfcnlerin iptali ger\xe7ekle\u015ftirilecek ise ilgili \xfcr\xfcn\xfcn packageItemId bilgisi itemIdList i\xe7erisinde kullan\u0131lmal\u0131d\u0131r.
- PUT
- https://api.tgoapis.com/integrator/order/meal/suppliers/
- supplierid
- /packages/unsupplied
- https://stageapi.tgoapis.com/integrator/order/meal/suppliers/
- packageId
- Paket id'si
- Paket item id listesi
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Restorana ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Değişiklik yapmak istediğiniz paket, kullandığınız supplierID ile ilişkili değildir.

## 8.trendyol-go-yemek-entegrasyonu/siparis-entegrasyonu/9.ymk-fatura-besleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/754405a6.9e3f6d7d.js`
- Module: `5112`

### Cikarilan metin / endpoint ipuclari

- POST
- Sipari\u015f Paketlerini \xc7ekme
- https://api.tgoapis.com/integrator/invoice/meal/suppliers/
- supplierId
- /supplier-invoice-links/
- https://stageapi.tgoapis.com/integrator/invoice/meal/suppliers/
