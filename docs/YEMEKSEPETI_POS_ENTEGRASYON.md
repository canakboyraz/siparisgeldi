# Yemeksepeti POS Entegrasyonu

Bu belge SiparisGeldi'nin Delivery Hero POS Integration Middleware ile Yemeksepeti siparislerini almasi ve yonetmesi icin uygulama notlarini icerir.

## Resmi kaynaklar

- POS entegrasyon sureci: https://developers.deliveryhero.com/documentation/pos.html#introduction
- Plugin API (Yemeksepeti'nin SiparisGeldi'ye yapacagi istekler): https://integration-middleware.stg.restaurant-partners.com/apidocs/pos-plugin-api
- Middleware API (SiparisGeldi'nin yapacagi istekler): https://integration-middleware.stg.restaurant-partners.com/apidocs/pos-middleware-api

## Mimari

Bu entegrasyon Partner API OAuth entegrasyonundan farklidir.

- Yemeksepeti yeni siparisi SiparisGeldi Plugin API adresine gonderir.
- SiparisGeldi istekteki JWT imzasini credential paketindeki `Secret` ile dogrular.
- Siparis hizla veritabanina kaydedilir ve `remoteOrderId` ile HTTP 200 donulur.
- Kabul, red, hazir ve teslim alma bildirimleri siparis payload'inda gelen callback URL'lerine gonderilir.
- Callback cagrilarinda `/v2/login` ile alinan Bearer token kullanilir.
- Ayni siparis yeniden gonderilirse yeni kayit ve ikinci yeni-siparis bildirimi olusturulmaz.

## Credential basvurusu

Resmi dokumandaki **Get Credentials** formundan POS credential talebi acilmalidir. Basvuru onaylandiginda PGP ile sifrelenmis su uc bilgi gelir:

- `Username`
- `Password`
- `Secret` (gelen Middleware JWT'lerini dogrulamak icin)

Basvuruda kullanilacak bilgiler:

| Alan | Deger |
|---|---|
| Firma / urun | SiparisGeldi |
| Resmi unvan | Erol Can Akboyraz |
| Ulke / platform | Turkiye / Yemeksepeti |
| Entegrasyon tipi | POS Plugin, Direct Flow talebi |
| Teknik iletisim | siparisgeldinet@gmail.com |
| Website | https://www.siparisgeldi.net |
| Plugin base URL | https://www.siparisgeldi.net/webhooks/yemeksepeti |
| Test ortami | Staging / Sandbox |

Direct Flow ayrica acikca talep edilmelidir. Direct Flow olmadan siparis once Yemeksepeti cihazinda kabul edilir; SiparisGeldi uzerinden kabul/red akisi kullanilamaz.

## Public PGP Key

Basvuru icin Public PGP Key zorunludur. Windows'ta Gpg4win/Kleopatra kurulup `siparisgeldinet@gmail.com` icin bir OpenPGP anahtar cifti olusturulabilir.

Kurallar:

- Forma yalnizca `-----BEGIN PGP PUBLIC KEY BLOCK-----` ile baslayan public key verilir.
- Private/secret key hicbir forma, mesaja, `.env` dosyasina veya Git reposuna konulmaz.
- Private key icin guclu bir parola belirlenir ve yedegi guvenli ortamda saklanir.
- Delivery Hero'nun sifreli credential mesaji yerel private key ile acilir.

## Plugin endpoint'leri

Delivery Hero'ya verilecek temel adres:

```text
https://www.siparisgeldi.net/webhooks/yemeksepeti
```

Uygulanan endpoint'ler:

```text
POST /webhooks/yemeksepeti/order/{remoteId}
PUT  /webhooks/yemeksepeti/remoteId/{remoteId}/remoteOrder/{remoteOrderId}/posOrderStatus
PUT  /webhooks/yemeksepeti/remoteId/{remoteId}/availability
```

Dispatch basari cevabi:

```json
{
  "remoteResponse": {
    "remoteOrderId": "123"
  }
}
```

HTTP `429` ve `5xx` cevaplar Delivery Hero tarafinda tekrar gonderime neden olur. Dokumana gore dispatch en fazla 10 kez, en az 30 saniyelik araliklarla tekrar denenebilir. Bu nedenle `token` bazli idempotency zorunludur.

## Siparis aksiyonlari

Payload'da ilgili callback URL varsa panelde su aksiyonlar gosterilir:

| Aksiyon | Callback | Gonderilen durum |
|---|---|---|
| Kabul et | `orderAcceptedUrl` | `order_accepted` |
| Reddet | `orderRejectedUrl` | `order_rejected` ve neden |
| Hazirlandi yap | `orderPreparedUrl` | Hazirlanma tamamlandi |
| Teslim alindi yap | `orderPickedUpUrl` | `order_picked_up` |

`order_accepted` ve `order_rejected` yalniz Direct Flow icin kullanilir. Callback URL payload'da yoksa o aksiyon gosterilmez. Platform kuryeli sipariste hazir bildirimi kurye cagirma amaciyla kullanilir. Teslim edildi durumu icin dokumanda genel bir manuel callback yoktur; terminal durum Yemeksepeti bildiriminden takip edilir.

## Railway degiskenleri

Credential geldikten sonra web servisine su degiskenler eklenir:

```text
YEMEKSEPETI_POS_USERNAME=<Delivery Hero username>
YEMEKSEPETI_POS_PASSWORD=<Delivery Hero password>
YEMEKSEPETI_POS_JWT_SECRET=<Delivery Hero secret>
YEMEKSEPETI_POS_CHAIN_CODE=<onboarding sirasinda verilen chain code>
```

Staging icin gerekirse:

```text
YEMEKSEPETI_POS_API_BASE=https://integration-middleware.stg.restaurant-partners.com
```

Canli base URL onboarding ekibinin verdigi kesin adresle ayarlanmalidir. Credential degerleri kullanici paneline veya Git'e yazilmaz.

## Test plani

1. Gecerli JWT ve bilinen `remoteId` ile test siparisi gonderilir.
2. Endpoint'in birkac saniye icinde HTTP 200 ve ayni `remoteOrderId` dondugu kontrol edilir.
3. Ayni payload tekrar gonderilir; tek siparis ve tek bildirim oldugu dogrulanir.
4. Urun, adet, fiyat, secenek, alt secenek, not, odeme, musteri, adres, telefon ve teslimat turu kontrol edilir.
5. Direct Flow siparisi panelden kabul edilir.
6. Yeni bir siparis teknik neden disinda gecerli bir nedenle reddedilir.
7. Platform kuryeli siparis hazir olarak isaretlenir.
8. Vendor delivery/pickup siparisi teslim alindi olarak isaretlenir.
9. Yemeksepeti tarafindan gelen iptal callback'i siparisi iptal durumuna getirir.
10. Gecersiz JWT, bilinmeyen `remoteId` ve gecersiz payload test edilir.

## Canliya gecis

Credential geldikten sonra test `remoteId` panelden kaydedilir ve staging testi yapilir. Test sonucuyla birlikte Plugin URL, Direct Flow talebi ve basarili senaryolar Yemeksepeti ekibine iletilir. Onaydan sonra canli Middleware base URL ayarlanir ve canli restoranlar kendi `remoteId` degerleriyle eslestirilir.
