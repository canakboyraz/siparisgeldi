# SiparişGeldi — Çok Kullanıcılı Yemek Sipariş Bildirim SaaS'ı

Restoranların Trendyol Go (ve yakında Migros Yemek / Getir) siparişlerini
web'den kaydolup kendi API bilgileriyle bağladıkları, siparişlerin **merkezi
bir Telegram botu** üzerinden anlık olarak telefonlarına düştüğü SaaS.

## Mimari

```
Web (Flask + Jinja)          Arka plan (APScheduler)
  ├─ Kayıt / Giriş             ├─ Her 30 sn: TrendyolGo sipariş polling
  ├─ Panel                     ├─ Her 5 sn : Telegram /start bağlama
  ├─ Platform kurulum          └─ 23:45   : Günlük özet raporu
  └─ Telegram bağla                    │
        │                              ▼
        └──────► SQLite/Postgres ◄──── Merkezi Telegram Botu ──► Kullanıcı
```

- **Merkezi bot modeli:** Tek bir Telegram botu. Kullanıcı panelde "Telegram'ı
  Bağla" der, `t.me/<bot>?start=<token>` linkine tıklar, `/start` ile chat_id'si
  otomatik yakalanıp hesabına bağlanır. Kullanıcı token'la uğraşmaz.
- **Güvenlik:** API secret'ları Fernet (AES) ile şifreli saklanır.

## Kurulum (geliştirme)

```bash
cd siparis_saas
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env içini doldur:
#   ENCRYPTION_KEY  → python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME → BotFather'dan (/newbot)

python app.py
# http://localhost:5000
```

Dev modda (`RUN_SCHEDULER=1`) web süreci arka plan işlerini de çalıştırır.

## Prod (ör. Railway / VPS)

`RUN_SCHEDULER=0` yapıp iki süreç çalıştır:

```bash
gunicorn wsgi:application --workers 1     # web
python worker.py                          # arka plan (tek instance!)
```

`DATABASE_URL` ile Postgres'e geç. Not: worker tek instance olmalı, aksi halde
polling ve bildirimler mükerrer olur.

## Test akışı

1. `/kayit` → hesap oluştur
2. Telegram'ı bağla (linke tıkla, botta Başlat'a bas)
3. Panel → Trendyol Go → API bilgilerini gir (test edilir + kaydedilir)
4. Worker 30 sn'de bir polling yapar; yeni sipariş → Telegram'a bildirim

## Yol haritası

- [x] Çok kullanıcılı çekirdek: kayıt/giriş, TrendyolGo, merkezi bot, polling, günlük rapor
- [x] Şifreli credential saklama
- [ ] Migros Yemek (webhook + Rijndael çözme) — endpoint iskeleti hazır
- [ ] Getir Yemek
- [ ] WhatsApp kanalı (Pro)
- [ ] Excel/PDF rapor indirme
- [ ] Ödeme/abonelik planları
```
