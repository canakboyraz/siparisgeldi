# 🚀 Railway'e Deploy (GitHub üzerinden)

Bu dosyadaki adımları kendi bilgisayarında (siparis_saas klasöründe) uygula.
Gizli anahtarları (SECRET_KEY, ENCRYPTION_KEY) buraya YAZMA — onlar Railway
panelindeki Variables kısmına girilir, repoya girmez.

---

## 1) GitHub deposu oluştur ve gönder

Terminalde, `siparis_saas` klasörünün içinde:

```bash
git init
git add .
git commit -m "SiparisGeldi - ilk sürüm"
git branch -M main
```

GitHub'da `siparisgeldi` adında **boş** bir repo aç (README ekleme), sonra:

```bash
git remote add origin https://github.com/<KULLANICI_ADIN>/siparisgeldi.git
git push -u origin main
```

> `.gitignore` sayesinde `.env` ve `*.db` gönderilmez — gizli bilgiler güvende.

---

## 2) Railway'de proje oluştur

1. Railway → **New Project** → **Deploy from GitHub repo**
2. `siparisgeldi` reposunu seç. Railway otomatik olarak Python projesi olarak
   algılar ve `Procfile`'daki `web` sürecini çalıştırır (gunicorn).

## 3) PostgreSQL ekle

1. Aynı proje içinde **New** → **Database** → **Add PostgreSQL**
2. Railway otomatik bir `DATABASE_URL` üretir.

## 4) Ortam değişkenleri (web servisi → Variables)

Aşağıdakileri gir (değerleri asistandan aldığın gizli anahtarlarla doldur):

| Değişken | Değer |
|---|---|
| `SECRET_KEY` | (asistanın verdiği) |
| `ENCRYPTION_KEY` | (asistanın verdiği — **sonradan değiştirme**, kayıtlı API key'ler okunamaz olur) |
| `TELEGRAM_BOT_TOKEN` | BotFather'dan (`/newbot`) |
| `TELEGRAM_BOT_USERNAME` | Botun kullanıcı adı (@ olmadan) |
| `RUN_SCHEDULER` | `1` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway referansı) |
| `MIGROS_API_BASE` | Test için `https://test.gourmet.migrosonline.com` |
| `MIGROS_WEBHOOK_USER` | (asistanın verdiği) |
| `MIGROS_WEBHOOK_PASS` | (asistanın verdiği) |
| `MIGROS_SECRET_KEY` | (şimdilik boş — Migros sonra verecek) |

> `PREFERRED_URL_SCHEME=https` ve `APP_DOMAIN=siparisgeldi.net` kodda varsayılan;
> istersen değişken olarak da ekleyebilirsin.

## 5) Deploy + geçici adres

- Railway otomatik deploy eder. **Settings → Networking → Generate Domain** ile
  `...up.railway.app` adresini al, tarayıcıda açıp landing sayfasını gör.

## 6) Kendi alan adın: siparisgeldi.net

1. Railway web servisi → **Settings → Networking → Custom Domain** → `siparisgeldi.net`
   (ve istersen `www.siparisgeldi.net`) ekle. Railway sana bir **CNAME hedefi** gösterir.
2. **Squarespace** → Domains → siparisgeldi.net → **DNS Settings** → Railway'in
   verdiği kaydı ekle:
   - `www` için: **CNAME** → (Railway'in verdiği hedef)
   - Kök alan (`@`) için: Railway'in yönergesine göre **A/ALIAS** kaydı ya da
     `www`'ye yönlendirme.
3. Birkaç dakika–saat içinde yayılır; HTTPS'i Railway otomatik verir.

> Kesin DNS kayıtları Railway'in gösterdiğine göre netleşir — o ekranı asistana
> iletirsen birebir hangi kaydı gireceğini söyler.

## 7) Deploy sonrası: Migros'a iletilecekler

Uygulama `https://siparisgeldi.net` üzerinde yayına girince Migros ekibine:

```
Order Created  : https://siparisgeldi.net/webhooks/migros/order-created
Order Canceled : https://siparisgeldi.net/webhooks/migros/order-canceled
Delivery Status: https://siparisgeldi.net/webhooks/migros/delivery-status
Basic Auth User: (MIGROS_WEBHOOK_USER değerin)
Basic Auth Pass: (MIGROS_WEBHOOK_PASS değerin)
```

Migros bunları alınca test restoranı + resmi Secret Key + API Key gönderir.
Secret Key'i `MIGROS_SECRET_KEY` değişkenine ekle; restoranın Store ID'sini de
panelden Migros Yemek sayfasına gir.

---

## Notlar

- **Tek servis yeterli:** Scheduler web süreci içinde çalışır (`RUN_SCHEDULER=1`,
  gunicorn `--workers 1`). Ayrı worker servisine şimdilik gerek yok.
- İleride yük artarsa: web'i `RUN_SCHEDULER=0` yapıp Procfile'daki `worker`
  sürecini ayrı bir Railway servisi olarak çalıştır (polling tek yerde olsun).
