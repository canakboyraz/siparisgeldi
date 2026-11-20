"""Demo hesabı: ziyaretçiye özel, örnek verilerle dolu geçici hesap.

- create_demo_user(): yeni bir demo kullanıcı + 30 günlük örnek sipariş,
  maliyet, komisyon ve gider verisi oluşturur.
- Demo hesapta platform API'sine giden işlemler kapalıdır; "Kabul et"
  yalnızca yerelde durumu değiştirir (bkz. app.py: demo_guard).
- cleanup_demo_users(): DEMO_TTL_HOURS'tan eski demo hesapları siler.
"""
import json
import random
import secrets
from datetime import date, datetime, timedelta

import pytz

from extensions import db

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
DEMO_TTL_HOURS = 12
DEMO_EMAIL_DOMAIN = "demo.siparisgeldi.invalid"

# ad: (satış fiyatı TL, birim maliyet TL, popülerlik ağırlığı)
MENU = {
    "Tavuk Dürüm": (150, 58, 9),
    "Et Dürüm": (210, 118, 6),
    "Izgara Köfte Porsiyon": (240, 132, 4),
    "Lahmacun": (85, 31, 6),
    "Patates Kızartması": (60, 19, 5),
    "Künefe": (140, 64, 3),
    "Ayran": (20, 24, 7),          # bilerek zararına: ambalajlı ayran maliyeti yüksek
    "Kola 330 ml": (45, 27, 5),
    "Şalgam": (35, 16, 2),
}
PLATFORM_WEIGHTS = [("trendyolgo", 6), ("migros", 4)]
COMMISSIONS = {"trendyolgo": 22.0, "migros": 18.0}
NOTES = ["Soğan olmasın", "Acılı olsun", "Zili çalmayın, kapıya bırakın", "Ekstra sos", "Peçete ekleyin"]

# Demo'da platforma gerçekten gidecek "Kabul et" yerine yerel durum değişikliği
DEMO_ACCEPT_STATUS = {"trendyolgo": "Picking", "migros": "Approved"}


def _utc(local_dt: datetime) -> datetime:
    return TURKEY_TZ.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)


def _pick(rng, weighted):
    names = [n for n, _ in weighted]
    weights = [w for _, w in weighted]
    return rng.choices(names, weights=weights, k=1)[0]


def _raw(platform: str, items: list) -> str:
    if platform == "migros":
        return json.dumps({"items": [{"name": n, "amount": q, "totalPrice": int(MENU[n][0] * q * 100)} for n, q in items],
                           "prices": {"total": {"amountAsPenny": int(sum(MENU[n][0] * q for n, q in items) * 100)}}},
                          ensure_ascii=False)
    return json.dumps({"lines": [{"name": n, "quantity": q, "price": MENU[n][0] * q} for n, q in items]},
                      ensure_ascii=False)


def _order(user_id, platform, number, status, when_utc, items, rng, note=None):
    from models import Order
    total = float(sum(MENU[n][0] * q for n, q in items))
    return Order(user_id=user_id, platform=platform, external_id=f"demo-{number}", order_number=str(number),
                 status=status, total_price=total, payment_type="Online",
                 customer_note=note, raw_json=_raw(platform, items), created_at=when_utc)


def _basket(rng):
    weighted = [(n, w) for n, (_, _, w) in MENU.items()]
    items = {}
    for _ in range(rng.choice([1, 2, 2, 3, 3, 4])):
        name = _pick(rng, weighted)
        items[name] = items.get(name, 0) + 1
    return list(items.items())


def create_demo_user():
    from models import (DailyAdvertisingExpense, Integration, MonthlyExpense, PlatformCommission,
                        PlatformExpense, ProductCost, User)
    now = datetime.utcnow()
    token = secrets.token_hex(5)
    user = User(email=f"demo-{token}@{DEMO_EMAIL_DOMAIN}", name="Lezzet Dürüm (Demo)", plan="pro",
                pro_started_at=now, pro_expires_at=now + timedelta(hours=DEMO_TTL_HOURS),
                is_demo=True, email_verified_at=now, notification_channel="telegram")
    user.set_password(secrets.token_urlsafe(24))
    db.session.add(user)
    db.session.flush()
    uid = user.id

    for platform in ("trendyolgo", "migros"):
        db.session.add(Integration(user_id=uid, platform=platform, is_active=True, last_sync_at=now,
                                   created_at=now - timedelta(days=40)))
    for platform, pct in COMMISSIONS.items():
        db.session.add(PlatformCommission(user_id=uid, platform=platform, percentage=pct))
    for name, (_, cost, _) in MENU.items():
        db.session.add(ProductCost(user_id=uid, platform="trendyolgo", product_key=name, product_name=name, unit_cost=cost))
    db.session.add(PlatformExpense(user_id=uid, platform="genel", name="Paket ve ambalaj", amount=7.5,
                                   expense_type="per_order", day_from=date(2020, 1, 1), day_to=date(2099, 12, 31)))

    today = datetime.now(TURKEY_TZ).date()
    db.session.add(MonthlyExpense(user_id=uid, month=today.replace(day=1), name="Kira", amount=28000))
    db.session.add(MonthlyExpense(user_id=uid, month=today.replace(day=1), name="Personel", amount=52000))

    rng = random.Random(token)
    number = 48000
    for back in range(30, 0, -1):
        day = today - timedelta(days=back)
        weekend = day.weekday() >= 4
        count = rng.randint(16, 24) + (8 if weekend else 0)
        if back % 4 == 0:
            db.session.add(DailyAdvertisingExpense(user_id=uid, day=day, amount=rng.choice([300, 400, 500])))
        for _ in range(count):
            hour = rng.choices([11, 12, 13, 14, 17, 18, 19, 20, 21, 22], weights=[3, 6, 6, 3, 3, 6, 9, 9, 6, 3])[0]
            when = _utc(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=rng.randint(0, 59)))
            platform = _pick(rng, PLATFORM_WEIGHTS)
            status = "Cancelled" if rng.random() < 0.04 else "Delivered"
            number += 1
            note = rng.choice(NOTES) if rng.random() < 0.15 else None
            db.session.add(_order(uid, platform, number, status, when, _basket(rng), rng, note))

    # Bugün: biri geciken, kabul bekleyen siparişler + hazırlananlar
    local_now = datetime.now(TURKEY_TZ).replace(tzinfo=None)
    today_orders = [
        ("trendyolgo", "Created", 1, [("Tavuk Dürüm", 2), ("Ayran", 2)], "Soğan olmasın"),
        ("migros", "NEW_PENDING", 4, [("Et Dürüm", 1), ("Künefe", 1)], None),
        ("trendyolgo", "Picking", 9, [("Lahmacun", 3), ("Şalgam", 2)], "Acılı olsun"),
        ("migros", "Approved", 14, [("Izgara Köfte Porsiyon", 1), ("Kola 330 ml", 1)], None),
    ]
    for back in range(1, 12):
        when = local_now - timedelta(minutes=25 + back * 31)
        if when.date() != today:
            break
        number += 1
        db.session.add(_order(uid, _pick(rng, PLATFORM_WEIGHTS), number, "Delivered", _utc(when), _basket(rng), rng))
    for platform, status, minutes, items, note in today_orders:
        number += 1
        db.session.add(_order(uid, platform, number, status, _utc(local_now - timedelta(minutes=minutes)), items, rng, note))

    db.session.commit()
    try:
        _seed_salon(user, rng)
    except Exception as exc:  # demo yine açılsın; salon verisi opsiyonel
        db.session.rollback()
        print(f"[DEMO] salon verisi eklenemedi: {exc}")
    return user


# QR menü demo verisi: kategori -> [(ad, fiyat, açıklama, alerjenler, kcal)]
SALON_MENU = [
    ("Dürümler", [
        ("Tavuk Dürüm", 150, "Közde tavuk, domates, marul, özel sos; lavaşta.", "gluten,sut", 520),
        ("Et Dürüm", 210, "Izgara dana eti, soğan, sumak, közlenmiş biber.", "gluten", 610),
        ("Lahmacun", 85, "İnce hamur, kıymalı harç; limon ve maydanozla.", "gluten", 380),
    ]),
    ("Yanında", [
        ("Patates Kızartması", 60, "Çıtır patates, isteğe göre ketçap ve mayonez.", None, 340),
    ]),
    ("Tatlı", [
        ("Künefe", 140, "Tel kadayıf, Hatay peyniri, şerbet; antep fıstığıyla.", "gluten,sut,findik", 560),
    ]),
    ("İçecekler", [
        ("Ayran", 20, "Soğuk, köpüklü ayran.", "sut", 110),
        ("Şalgam", 35, "Acılı ya da acısız.", None, 30),
        ("Kola 330 ml", 45, "Kutu.", None, 140),
    ]),
]


def _seed_salon(user, rng):
    """Demo: QR menü, masalar, masa siparişleri, garson çağrısı ve sayım."""
    import menu as menu_mod
    import stock as stock_mod
    from models import (MenuCategory, MenuItem, StockCount, StockCountLine, StockItem, TableCall,
                        TableOrder, TableOrderLine)
    setting = menu_mod.get_setting(user, create=True)
    setting.welcome = "Masadaki QR ile sipariş ver, garsonu tek dokunuşla çağır."
    items = {}
    for ci, (cat_name, rows) in enumerate(SALON_MENU):
        cat = MenuCategory(user_id=user.id, name=cat_name, sort=(ci + 1) * 10)
        db.session.add(cat)
        db.session.flush()
        for ii, (name, price, desc, allergens, kcal) in enumerate(rows):
            item = MenuItem(user_id=user.id, category_id=cat.id, name=name, price=price, description=desc,
                            allergens=allergens, calories=kcal, sort=(ii + 1) * 10)
            db.session.add(item)
            items[name] = item
    db.session.flush()
    menu_mod.add_tables(user, "Masa", 1, 6)
    from models import MenuTable
    tables = MenuTable.query.filter_by(user_id=user.id).order_by(MenuTable.sort).all()
    now = datetime.utcnow()
    for table, status, minutes, lines in ((tables[1], "new", 3, [("Tavuk Dürüm", 2), ("Ayran", 2)]),
                                          (tables[3], "preparing", 11, [("Lahmacun", 3), ("Şalgam", 3)])):
        order = TableOrder(user_id=user.id, table_id=table.id, table_name=table.name, status=status,
                           created_at=now - timedelta(minutes=minutes), updated_at=now - timedelta(minutes=minutes))
        total = 0
        db.session.add(order)
        db.session.flush()
        for name, qty in lines:
            it = items[name]
            db.session.add(TableOrderLine(order_id=order.id, item_id=it.id, name=name, price=it.price, quantity=qty))
            total += float(it.price) * qty
        order.total = total
    db.session.add(TableCall(user_id=user.id, table_id=tables[4].id, table_name=tables[4].name, kind="garson",
                             status="open", created_at=now - timedelta(minutes=1)))
    stock_mod.get_setting(user, create=True)
    stock_mod.seed_default(user)
    yesterday = datetime.now(TURKEY_TZ).date() - timedelta(days=1)
    count = StockCount(user_id=user.id, count_date=yesterday, counted_by="Ayşe (barista)",
                       created_at=now - timedelta(hours=14))
    db.session.add(count)
    db.session.flush()
    for i, it in enumerate(StockItem.query.filter_by(user_id=user.id).all()):
        low = i % 5 == 0 and it.min_stock
        counted = (it.min_stock or 4) * (0.5 if low else rng.uniform(1.4, 3.0))
        db.session.add(StockCountLine(count_id=count.id, item_id=it.id, category_name=it.category.name if hasattr(it, "category") and it.category else "",
                                      item_name=it.name, unit=it.unit, min_stock=it.min_stock,
                                      prev_qty=round(counted + rng.uniform(1, 4)), received=0, counted=round(counted, 1)))
    db.session.commit()


def delete_user_data(user):
    from models import (DailyAdvertisingExpense, MonthlyExpense, Payment, PlatformCommission,
                        PlatformExpense, ProductCost, ProductAlias, MenuSetting, MenuCategory, MenuItem,
                        MenuTable, TableOrder, TableOrderLine, TableCall, StockSetting, StockCategory,
                        StockItem, StockCount, StockCountLine)
    order_ids = [o.id for o in TableOrder.query.filter_by(user_id=user.id).all()]
    if order_ids:
        TableOrderLine.query.filter(TableOrderLine.order_id.in_(order_ids)).delete(synchronize_session=False)
    count_ids = [c.id for c in StockCount.query.filter_by(user_id=user.id).all()]
    if count_ids:
        StockCountLine.query.filter(StockCountLine.count_id.in_(count_ids)).delete(synchronize_session=False)
    for model in (TableOrder, TableCall, MenuItem, MenuCategory, MenuTable, MenuSetting,
                  StockCount, StockItem, StockCategory, StockSetting, ProductAlias):
        model.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    for model in (ProductCost, PlatformExpense, PlatformCommission, DailyAdvertisingExpense, MonthlyExpense, Payment):
        model.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.delete(user)  # sipariş ve entegrasyonlar cascade ile silinir


def cleanup_demo_users(app=None, ttl_hours: int = DEMO_TTL_HOURS) -> int:
    def run():
        from models import User
        limit = datetime.utcnow() - timedelta(hours=ttl_hours)
        old = User.query.filter(User.is_demo.is_(True), User.created_at < limit).all()
        for user in old:
            delete_user_data(user)
        db.session.commit()
        return len(old)
    if app is None:
        return run()
    with app.app_context():
        return run()
