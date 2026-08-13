# Trendyol Go Market Entegrasyonu Yerel Arsiv

Kaynak kategori: https://developers.tgoapps.com/docs/category/7-uber-eats-trendyol-go---market-entegrasyonu

Not: Bu dosya Docusaurus JS bundle icinden cikarilmis yerel calisma arsividir. Gizli bilgi icermez.

## 7.trendyol-go-hizli-market-entegrasyonu/iade-entegrasyonu/1.hm-iadesi-olusan-siparisleri-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/16790e54.06b9f2e8.js`
- Module: `8139`

### Cikarilan metin / endpoint ipuclari

- Tekil veya \xe7o\u011ful olarak ilgili iade paketlerinin detaylar\u0131na ula\u015fabilirsiniz.
- claimItemStatus
- Belirli bir tarihten sonraki onaylanan iadeleri getirir. Timestamp (milliseconds) olarak g\xf6nderilmelidir.
- Belirtilen tarihe kadar olan onaylanan iadeleri getirir. Timestamp (milliseconds) olarak g\xf6nderilmelidir.
- Status
- Reddedilen iade paketleri Rejected stat\xfcs\xfcnde olur.
- Kabul edilen iadelerin stat\xfcleri Accepted olur.
- GET getClaims
- https://api.tgoapis.com/integrator/claim/grocery/suppliers/
- /claims?claimItemStatus=
- https://stageapi.tgoapis.com/integrator/claim/grocery/suppliers/
- SKT - Ge\xe7mi\u015f \xdcr\xfcn Teslimat\u0131
- status

## 7.trendyol-go-hizli-market-entegrasyonu/iade-entegrasyonu/2.hm-iade-talebi-olusturma.md

- Chunk: `https://developers.tgoapps.com/assets/js/4b6d9dd1.714beb04.js`
- Module: `1272`

### Cikarilan metin / endpoint ipuclari

- ,null,'Oluşturacağınız iade talebi
- POST createClaim
- https://api.tgoapis.com/integrator/claim/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/claim/grocery/suppliers/
- SKT - Ge\xe7mi\u015f \xdcr\xfcn Teslimat\u0131
- SKT - Yakla\u015fm\u0131\u015f \xdcr\xfcn Teslimat\u0131
- Ge\xe7 Teslim Edilmi\u015f
- Teslim alınmamış sipariş

## 7.trendyol-go-hizli-market-entegrasyonu/iade-entegrasyonu/3.hm-iade-onaylama-reddetme.md

- Chunk: `https://developers.tgoapps.com/assets/js/98094552.5a332b5b.js`
- Module: `3736`

### Cikarilan metin / endpoint ipuclari

- PUT claimAccept
- https://api.tgoapis.com/integrator/claim/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/claim/grocery/suppliers/
- PUT claimReject
- Sat\u0131c\u0131 iade talebi i\xe7in g\xf6r\xfc\u015f vermedi
- Fi\u015f m\xfc\u015fteriye yeniden g\xf6nderildi, iade yap\u0131lmayacak

## 7.trendyol-go-hizli-market-entegrasyonu/iade-entegrasyonu/4.hm-iadeye-itiraz-etme.md

- Chunk: `https://developers.tgoapps.com/assets/js/9b6aa0f9.be71050a.js`
- Module: `5788`

### Cikarilan metin / endpoint ipuclari

- GET getObjectionableItems
- https://api.tgoapis.com/integrator/claim/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/claim/grocery/suppliers/
- POST createObjection

## 7.trendyol-go-hizli-market-entegrasyonu/market-degerlendirme-entegrasyonu/market-scorelar\u0131n\u0131-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/586aa65b.7ce537b1.js`
- Module: `7415`

### Cikarilan metin / endpoint ipuclari

- Market Genel De\u011ferlendirmelerini \xc7ekme Servisi
- Method GET
- https://api.tgoapis.com/integrator/review/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/review/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/market-degerlendirme-entegrasyonu/market-yorumlari-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/f23625ed.0411a8eb.js`
- Module: `9774`

### Cikarilan metin / endpoint ipuclari

- Market De\u011ferlendirme ve Yorumlar\u0131n\u0131 \xc7ekme Servisi
- Method GET
- https://api.tgoapis.com/integrator/review/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/review/grocery/suppliers/
- sellerAnswerStatus
- status

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/1.hm-teslimat-bolgesi-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/e4b24e25.3bd05886.js`
- Module: `2932`

### Cikarilan metin / endpoint ipuclari

- Teslimat B\xf6lgesi Bildirimi
- PUT areas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/2.hm-teslimat-suresi-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/8fe4004d.864df4a9.js`
- Module: `8673`

### Cikarilan metin / endpoint ipuclari

- Teslimat S\xfcresi Bildirimi
- PUT eta
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/3.hm-calisma-durumu-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/2215b488.f14c487a.js`
- Module: `2995`

### Cikarilan metin / endpoint ipuclari

- ,null,'workingStatus :
- GET workingStatus
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/working-status
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- PUT workingStatus
- /stores/
- storeId
- /working-status
- workingStatus

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/4.hm-coklu-teslimat-bolgesi-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/ae661511.0c47faa9.js`
- Module: `3650`

### Cikarilan metin / endpoint ipuclari

- \xc7oklu Teslimat B\xf6lgesi Bildirimi
- PUT updateMarketDeliveryAreas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Markete ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/5.hm-coklu-teslimat-bolgesi-listeleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/430b1686.3cd4bd9a.js`
- Module: `8151`

### Cikarilan metin / endpoint ipuclari

- \xc7oklu Teslimat B\xf6lgesi Listeleme
- GET getMarketDeliveryAreas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- status
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Markete ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/6.hm-coklu-teslimat-bolgesi-bildirimi-v2.md

- Chunk: `https://developers.tgoapps.com/assets/js/bc7ccdb0.03c84203.js`
- Module: `627`

### Cikarilan metin / endpoint ipuclari

- \xc7oklu Teslimat B\xf6lgesi Bildirimi V2
- Teslimat B\xf6lgesi Bildirimi V2 ve Teslimat B\xf6lgesi Listeleme V2 servisleri, entegrat\xf6r taraf\u0131ndan integratorId g\xf6nderilebilmesi i\xe7in geli\u015ftirilmi\u015ftir. Bildirim ve listeleme i\xe7in V2 servislerinin kullan\u0131lmas\u0131 durumunda di\u011fer bildirim ve listeleme servisleri kullan\u0131lmamal\u0131d\u0131r.
- integratorId:
- integratorId
- 1. Teslimat B\xf6lgesi Olu\u015fturma
- POST createDeliveryAreas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- status
- Teslimat b\xf6lgeleri listesi
- areas.status
- areas.integratorId
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Teslimat b\xf6lgeleri ba\u015far\u0131yla olu\u015fturulmu\u015ftur. Yan\u0131tta her b\xf6lge i\xe7in
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- 2. Teslimat B\xf6lgesi ETA G\xfcncelleme
- PUT deliveryAreasEtaUpdate
- 3. Teslimat B\xf6lgesi Minimum Sepet Tutar\u0131 G\xfcncelleme
- PUT deliveryAreasMbsUpdate
- 4. Teslimat B\xf6lgesi Stat\xfc G\xfcncelleme
- PUT deliveryAreasStatusUpdate
- /v2/delivery-areas/status
- deliveryAreasStatus
- deliveryAreasStatus.areaId
- deliveryAreasStatus.status
- 5. Teslimat B\xf6lgesi Koordinat G\xfcncelleme
- PUT deliveryAreasUpdate
- 6. Teslimat B\xf6lgesi Silme
- DELETE deliveryAreasDelete

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/7.hm-calisma-saatlerinin-guncellenmesi.md

- Chunk: `https://developers.tgoapps.com/assets/js/531f7edd.e7c20f7c.js`
- Module: `8970`

### Cikarilan metin / endpoint ipuclari

- PUT updateGroceryWorkingHours
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Markete ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/8.hm-coklu-teslimat-bolgesi-listeleme-v2.md

- Chunk: `https://developers.tgoapps.com/assets/js/3287bd9b.c7a83034.js`
- Module: `2600`

### Cikarilan metin / endpoint ipuclari

- \xc7oklu Teslimat B\xf6lgesi Listeleme V2
- \xc7oklu Teslimat B\xf6lgesi Listeleme
- Teslimat B\xf6lgesi Bildirimi V2 ve Teslimat B\xf6lgesi Listeleme V2 servisleri, entegrat\xf6r taraf\u0131ndan integratorId g\xf6nderilebilmesi i\xe7in geli\u015ftirilmi\u015ftir. Bildirim ve listeleme i\xe7in V2 servislerinin kullan\u0131lmas\u0131 durumunda di\u011fer bildirim ve listeleme servisleri kullan\u0131lmamal\u0131d\u0131r.
- GET getMarketDeliveryAreas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- status
- integratorId
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Markete ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/hemen-teslimat/9.hm-market-bilgilerin-alinmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/cd6e0cc9.c413e474.js`
- Module: `8490`

### Cikarilan metin / endpoint ipuclari

- Marketlerin Bilgilerinin Alınması
- GET retrieveGroceriesOfSeller
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierid
- /store-listing
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Market
- supplierId
- workingStatus
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Markete ait kategorinin stat\xfcs\xfc istekte g\xf6nderilen stat\xfcye ge\xe7ecektir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/randevulu-teslimat/1.hm-calisma-durumu-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/11c5eb02.6c64e17f.js`
- Module: `1717`

### Cikarilan metin / endpoint ipuclari

- },'workingStatus :
- GET workingStatus
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/working-status
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- PUT workingStatus
- /stores/
- storeId
- /working-status
- workingStatus

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/randevulu-teslimat/2.hm-slot-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/c7f73354.7987640a.js`
- Module: `6804`

### Cikarilan metin / endpoint ipuclari

- PUT slots
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Şube id (storeId)

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/randevulu-teslimat/3.hm-teslimat-bolgesi-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/254e486c.ae43af0f.js`
- Module: `1217`

### Cikarilan metin / endpoint ipuclari

- Teslimat B\xf6lgesi Bildirimi
- PUT areas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Şube id (storeId)

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/randevulu-teslimat/4.hm-slotlari-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/fb918feb.7c51af76.js`
- Module: `4609`

### Cikarilan metin / endpoint ipuclari

- GET slots
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Şube id (storeId)

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/randevulu-teslimat/5.hm-teslimat-bolgelerini-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/3aa31c2a.8e10f0f1.js`
- Module: `7292`

### Cikarilan metin / endpoint ipuclari

- Teslimat B\xf6lgelerini \xc7ekme
- GET areas
- https://api.tgoapis.com/integrator/store/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/store/grocery/suppliers/
- Şube id (storeId)

## 7.trendyol-go-hizli-market-entegrasyonu/market-entegrasyonu/teslimat-ucreti/1.hm-magaza-teslimat-ucreti.md

- Chunk: `https://developers.tgoapps.com/assets/js/0df276ee.00727a6a.js`
- Module: `1807`

### Cikarilan metin / endpoint ipuclari

- Teslimat \xdccreti
- Teslimat \xfccreti kurallar\u0131 ma\u011faza (storeId) bazl\u0131 tan\u0131mlan\u0131r.
- PUT endpoint'i upsert mant\u0131\u011f\u0131 ile \xe7al\u0131\u015f\u0131r. Mevcut bir kural varsa g\xfcncellenir, yoksa olu\u015fturulur.
- Teslimat \xdccreti Kural\u0131 Sorgulama
- GET shipping-rule
- https://api.tgoapis.com/integrator/shipping-api/shipping-rule/stores/
- storeId
- https://stageapi.tgoapis.com/integrator/shipping-api/shipping-rule/stores/
- supplier-id
- Teslimat \xfccreti kurallar\u0131 listesi. Minimum sepet tutar\u0131na g\xf6re kademeli olarak teslimat \xfccreti tan\u0131mlanabilir.
- Teslimat \xdccreti Kural\u0131 Olu\u015fturma/G\xfcncelleme
- PUT shipping-rule
- Status Code
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Teslimat \xfccreti kural\u0131 ba\u015far\u0131yla olu\u015fturulmu\u015f veya g\xfcncellenmi\u015ftir.
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere Uber Eats Trendyol Go Sat\u0131c\u0131 Paneli \xfczerinden ula\u015fabilirsiniz.
- Teslimat \xdccreti Kural\u0131 Silme
- DELETE shipping-rule
- G\xf6nderilen istek ba\u015far\u0131l\u0131 olmu\u015ftur. Teslimat \xfccreti kural\u0131 ba\u015far\u0131yla silinmi\u015ftir.
- Senaryo 1: Sepet Tutar\u0131na G\xf6re Kademeli Teslimat \xdccreti
- Senaryo 2: Sabit Teslimat \xdccreti
- Senaryo 3: \xdccretsiz Teslimat

## 7.trendyol-go-hizli-market-entegrasyonu/musteri-arama-entegrasyonu/1.musteri-arama-servisinin-cagirilmasi.md

- Chunk: `https://developers.tgoapps.com/assets/js/a1681e38.3361d63e.js`
- Module: `4674`

### Cikarilan metin / endpoint ipuclari

- POST
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- supplierId
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/
- Paket numarası

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/1.hm-test-siparisi-olusturma.md

- Chunk: `https://developers.tgoapps.com/assets/js/0ae24be7.aa4e161f.js`
- Module: `8564`

### Cikarilan metin / endpoint ipuclari

- POST
- https://stageapi.tgoapis.com/integrator/grocery-test-order/orders/instant
- store
- storeId

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/2.hm-yeni-siparis-paketlerini-cekme.md

- Chunk: `https://developers.tgoapps.com/assets/js/3f5d0018.e8948dc4.js`
- Module: `8059`

### Cikarilan metin / endpoint ipuclari

- Yeni Sipari\u015f Paketlerini \xc7ekme
- Sipari\u015f Paketleri \xc7ekme S\xfcresi:
- },'Paketi b\xf6l\xfcnm\xfc\u015f olan sipari\u015fleri \xe7ekerken
- },'Sipari\u015f Paketlerini \xe7ekme servisinden Model 2 (Uber Eats Trendyol Go kuryesi ile teslimat yapan sat\u0131c\u0131lar) i\xe7in
- Teslimat \xdccreti
- GET
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- supplierId
- /packages
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/
- /packages/ids?id=
- /packages/order-number/
- \xd6nerilen Endpoint
- https://api.tgoapis.com/integrator/order/grocery/suppliers/123456/packages?storeId=164&status=Shipped&status=Delivered&sortDirection=DESC
- storeId
- status
- packageStatus
- Trendyol Hızlı Market
- packageItemId
- supplierType

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/3.hm-paket-statu-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/ea1b373c.bab38310.js`
- Module: `9094`

### Cikarilan metin / endpoint ipuclari

- Paket Stat\xfc Bildirimi (updatePackage)
- Provizyon Aralığı Bilgisinin Alınması (GET invoiceAmount)
- Buradaki \xf6nemli nokta sipari\u015f haz\u0131rland\u0131 bildirimi(Invoiced) ad\u0131m\u0131ndan hemen \xf6nce provizyon aral\u0131\u011f\u0131n\u0131 \xe7ekip(GET invoiceAmount) daha sonra sipari\u015f haz\u0131rland\u0131 bildirimi(Invoiced) yap\u0131lmas\u0131d\u0131r.
- PUT
- Endpoint'e kullan\u0131m\u0131nda request body g\xf6nderilmeyecektir
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- supplierid
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/
- Invoice statusu beslenmeyen sipari\u015fler shipped durumuna ge\xe7irilememektedir.
- GET
- supplierId

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/4.hm-tedarik-edememe-bildirimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/9dabf357.d614a36a.js`
- Module: `758`

### Cikarilan metin / endpoint ipuclari

- Tedarik edememe bildirimi yap\u0131ld\u0131\u011f\u0131nda, Uber Eats Trendyol Go Order Management System taraf\u0131ndan ayn\u0131 orderNumber \xfczerinde yeni bir ShipmentPackageID olu\u015fturulur ve \xf6nceki shipmentpackage iptal edilir. Tedarik edememe kayd\u0131 yap\u0131ld\u0131ktan sonra tekrar
- Sipari\u015f Paketlerini \xc7ekme
- PUT
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/5.hm-alternatif-teslimat-ile-gonderim.md

- Chunk: `https://developers.tgoapps.com/assets/js/f65369f0.c7575e4a.js`
- Module: `4722`

### Cikarilan metin / endpoint ipuclari

- Alternatif Teslimat \u0130le G\xf6nderim
- PUT
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/
- manualDelivered (Sipariş Teslim Edildi Bildrimi)

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/6.hm-alternatif-urun-gonderimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/178acdc2.cb17177c.js`
- Module: `8090`

### Cikarilan metin / endpoint ipuclari

- },'Tedarik edememe işlemi sonrasında oluşan yeni packageId ile
- : G\xf6nderilmesi gereken \xfcr\xfcn yerine alternatif \xfcr\xfcn olarak g\xf6nderilen barkodlara ait packageItemIdList.')),(0,i.kt)(
- PUT
- https://api.tgoapis.com/integrator/order/grocery/suppliers/
- /packages/
- packageId
- https://stageapi.tgoapis.com/integrator/order/grocery/suppliers/
- Birden fazla alternatif \xfcr\xfcn g\xf6nderilecek ise say\u0131s\u0131 kadar packageItemId'leri ile obje olu\u015fturmal\u0131s\u0131n\u0131z.

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/7.hm-fatura-gonderimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/aa3f44a5.5c9e79f5.js`
- Module: `9168`

### Cikarilan metin / endpoint ipuclari

- POST
- https://api.tgoapis.com/integrator/invoice/grocery/suppliers/
- supplierId
- /supplier-invoice-links/instant
- https://stageapi.tgoapis.com/integrator/invoice/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/siparis-entegrasyonu/8.hm-fatura-silme.md

- Chunk: `https://developers.tgoapps.com/assets/js/65291488.766f5ff0.js`
- Module: `9949`

### Cikarilan metin / endpoint ipuclari

- METHOD: POST
- https://api.tgoapis.com/integrator/invoice/grocery/suppliers/
- supplierId
- /supplier-invoice-links/delete

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/1.hm-urun-aktarimi.md

- Chunk: `https://developers.tgoapps.com/assets/js/c9053008.20fc67f9.js`
- Module: `915`

### Cikarilan metin / endpoint ipuclari

- POST
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/
- Status Code
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/10.hm-urun-denetim-bilgileri.md

- Chunk: `https://developers.tgoapps.com/assets/js/1dc40fac.25db0f53.js`
- Module: `2933`

### Cikarilan metin / endpoint ipuclari

- POST
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/11.hm-hata-kodlari-ve-sorun-giderme.md

- Chunk: `https://developers.tgoapps.com/assets/js/c4951759.c40ec9bf.js`
- Module: `2604`

### Cikarilan metin / endpoint ipuclari

- HTTP Status Kodları
- Status Code
- supplierID, API Key veya API Secret Key bilgilerinden biri eksik ya da yanl\u0131\u015f. Ayr\u0131ca, farkl\u0131 bir sat\u0131c\u0131ya ait kayna\u011fa eri\u015fmeye \xe7al\u0131\u015f\u0131yorsan\u0131z da bu hata d\xf6n\xfcl\xfcr.
- Endpoint i\xe7in yanl\u0131\u015f HTTP metodu kullan\u0131lm\u0131\u015f. \xd6rne\u011fin POST yerine GET g\xf6nderilmi\u015f olabilir.
- API Key / Secret Key hatalı ya da supplierId size ait değil.

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/2.hm-trendyol-kategori-bilgileri.md

- Chunk: `https://developers.tgoapps.com/assets/js/9ebeb664.06763f82.js`
- Module: `3941`

### Cikarilan metin / endpoint ipuclari

- GET
- https://api.tgoapis.com/integrator/product/grocery/categories
- https://stageapi.tgoapis.com/integrator/product/grocery/categories
- https://api.tgoapis.com/integrator/product/grocery/categories?page=0&size=200
- https://api.tgoapis.com/integrator/product/grocery/categories?page=0&size=200&withSellerAttributes=true&leaf=true

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/3.hm-trendyol-marka-bilgileri.md

- Chunk: `https://developers.tgoapps.com/assets/js/614fcba2.86c8ba35.js`
- Module: `9747`

### Cikarilan metin / endpoint ipuclari

- GET
- https://api.tgoapis.com/integrator/product/grocery/brands
- https://stageapi.tgoapis.com/integrator/product/grocery/brands
- \xd6rnek istek: https://api.tgoapis.com/integrator/product/grocery/brands?page=1&size=200
- https://api.tgoapis.com/integrator/product/grocery/brands/by-name?name=
- https://stageapi.tgoapis.com/integrator/product/grocery/brands/by-name?name=

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/4.hm-urun-filtreleme-v2.md

- Chunk: `https://developers.tgoapps.com/assets/js/94b710c6.52170c84.js`
- Module: `7377`

### Cikarilan metin / endpoint ipuclari

- GET
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- supplierId
- /stores/
- storeId
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/5.hm-urun-bilgisi-guncelleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/6325d39c.96f1d6d5.js`
- Module: `3570`

### Cikarilan metin / endpoint ipuclari

- PUT
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/6.hm-sube-bazli-urun-fiyat-stok-guncelleme.md

- Chunk: `https://developers.tgoapps.com/assets/js/e2953b16.a0fb196a.js`
- Module: `9717`

### Cikarilan metin / endpoint ipuclari

- \u015eu an i\xe7in \u015fube isimlerine ait ID de\u011ferlerini kategori sorumlular\u0131n\u0131zdan temin etmeniz gerekmektedir. \u0130lerleyen d\xf6nemlerde storeId bilgilerinizi \xe7ekece\u011finiz servisimiz sizlerin kullan\u0131m\u0131na a\xe7\u0131lacakt\u0131r.
- POST
- storeupdatePriceAndInventory
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/
- storeId

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/7.hm-toplu-islem-kontrolu.md

- Chunk: `https://developers.tgoapps.com/assets/js/1afa2e20.10003c0b.js`
- Module: `3119`

### Cikarilan metin / endpoint ipuclari

- GET
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/
- supplierId
- status
- API

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/8.hm-bundle-urunler.md

- Chunk: `https://developers.tgoapps.com/assets/js/11eb6f26.bffab733.js`
- Module: `6653`

### Cikarilan metin / endpoint ipuclari

- POST
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/
- items[].storeIds
- storeIds
- Status Code
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere

## 7.trendyol-go-hizli-market-entegrasyonu/urun-entegrasyonu/9.hm-urun-satisa-acma-kapama.md

- Chunk: `https://developers.tgoapps.com/assets/js/185e7dd8.3e8dee34.js`
- Module: `6057`

### Cikarilan metin / endpoint ipuclari

- storeId
- PUT
- https://api.tgoapis.com/integrator/product/grocery/suppliers/
- supplierId
- https://stageapi.tgoapis.com/integrator/product/grocery/suppliers/
- items[].storeId
- Status Code
- \u0130stek g\xf6nderirken kulland\u0131\u011f\u0131n\u0131z supplierID, API Key, API Secure Key bilgilerinden birisi eksik ya da yanl\u0131\u015ft\u0131r. Ma\u011fazan\u0131z i\xe7in do\u011fru bilgilere
