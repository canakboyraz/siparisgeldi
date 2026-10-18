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
| `MIGROS_API_BASE` | Canlı için `https://gourmet.migrosone.com` |
| `MIGROS_WEBHOOK_USER` | (asistanın verdiği) |
| `MIGROS_WEBHOOK_PASS` | (asistanın verdiği) |
| `MIGROS_SECRET_KEY` | Migros’un canlı ortam için verdiği Secret Key |

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

---

## 8) Ölçek ve izleme (yeni)

### Worker'ı ayrı servise al (önerilen, 20+ restoranda şart)

1. Railway → aynı projede **New → GitHub Repo** ile aynı repodan ikinci servis aç, adı `worker`.
2. Worker servisi → Settings → **Custom Start Command**: `python worker.py`
3. Worker servisine web servisiyle **aynı Variables**'ı gir (en kolayı: Shared Variables).
4. Web servisinde `RUN_SCHEDULER=0` yap. Worker'da `RUN_SCHEDULER` önemsiz (kendisi başlatır).
5. Worker **tek instance** kalmalı (Replicas = 1), yoksa bildirimler mükerrer olur.

Polling artık entegrasyonları paralel işler (`POLL_MAX_WORKERS`, varsayılan 8);
yavaş yanıt veren bir restoran diğerlerinin bildirimini geciktirmez.

### Sağlık kontrolü

- `https://siparisgeldi.net/healthz` → 200 ise DB ve worker çalışıyor; 503 ise
  DB'ye ulaşılamıyor ya da worker 3 dakikadır sessiz.
- UptimeRobot (ücretsiz) → New Monitor → HTTP(s) → bu adres, 5 dk aralık,
  alarm: e-posta/Telegram.

### Senkron alarmı

Worker her 5 dakikada polling yapılan entegrasyonları kontrol eder;
`SYNC_STALE_ALERT_MINUTES` (10 dk) boyunca senkron olmayan varsa yöneticiye
Telegram mesajı gelir (aynı entegrasyon için saatte en fazla 1 kez). Alarmın
gelmesi için `ADMIN_EMAILS` hesabının panelden Telegram'ı bağlamış olması
ya da `ADMIN_ALERT_TELEGRAM_CHAT_IDS` girilmiş olması gerekir.

### Sentry (hata takibi)

sentry.io'da ücretsiz Flask projesi aç → DSN'i `SENTRY_DSN` olarak gir.

### E-posta

Şifre sıfırlama ve e-posta doğrulama için `SMTP_*` değişkenlerini gir
(bkz. `.env.example`). SMTP girilmezse sıfırlama bağlantısı yalnızca
kullanıcının bağlı Telegram'ına gider.
