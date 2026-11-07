"""Günlük stok sayımı: kurallar ve yardımcılar.

Barista hesapsız bir bağlantıdan (isteğe bağlı PIN) tarih + adını girip ürünleri sayar.
İşletme sahibi panelde sonuçları, sipariş verilecekleri ve kullanım/fireyi görür;
kategori ve ürünleri yönetir.

Kullanılan / fire = önceki sayımda sayılan + bugün gelen − şimdi sayılan
Sipariş ver      = sayılan ≤ min. stok
"""
import re
import secrets
from datetime import date, datetime, timedelta

from extensions import db
from models import StockCategory, StockCount, StockCountLine, StockItem, StockSetting

UNITS = ("adet", "şişe", "kg", "gr", "litre", "paket", "kutu", "dilim", "koli")
COOKIE_PREFIX = "sg_sayim_"

# Örnek kafe listesi (Pion'un Excel sayım formundan): (kategori, [(ürün, birim, min)])
DEFAULT_LIST = [
    ("Şuruplar", [("Vanilya şurubu", "şişe", 1), ("Karamel şurubu", "şişe", 1), ("Toffee Nut şurubu", "şişe", 1),
                  ("Balkabağı (Pumpkin) şurubu", "şişe", 1), ("Mante Cubana şurubu", "şişe", 1), ("Cool Lime", "şişe", 1),
                  ("Berry Hibiscus", "şişe", 1), ("Dragon Mango", "şişe", 1), ("Orange Mango", "şişe", 1),
                  ("Çilek şurubu", "şişe", 1), ("Tiramisu şurubu", "şişe", 1), ("Kuzu Kulağı", "şişe", 1)]),
    ("Püreler", [("Çilek püresi", "adet", 1), ("Mango püresi", "adet", 1), ("Yaban mersini püresi", "adet", 1),
                 ("Kavun püresi", "adet", 1)]),
    ("Soslar", [("Karamel sos", "adet", 1), ("Çikolata sos", "adet", 1), ("Salted karamel sos", "adet", 1),
                ("Beyaz çikolata sos", "adet", 1)]),
    ("Tatlılar", [("San Sebastian", "dilim", 1), ("Brownie", "adet", 1), ("Tiramisu", "adet", 1), ("Lotus Cup", "adet", 1),
                  ("Magnolia Cup", "adet", 1), ("Marlenka", "dilim", 1), ("Cookie", "adet", 1), ("Cookie Pie", "adet", 1),
                  ("Nata", "adet", 1), ("Dondurma sade", "adet", 1), ("Dondurma kakao", "adet", 1),
                  ("Waffle hamuru", "adet", 1), ("Kıtır waffle", "kg", 1)]),
    ("Sandviçler", [("Türk sandviç", "adet", 1), ("3 peynirli sandviç", "adet", 1), ("İtalyan sandviç", "adet", 1),
                    ("Bagel roastbeef", "adet", 1), ("Ezine-hindi füme", "adet", 1)]),
    ("Kahve çekirdekleri", [("Espresso", "kg", 3), ("Filtre kahve", "kg", 2), ("Colombia", "kg", 1),
                            ("Türk kahvesi", "kg", 1), ("Dibek kahvesi", "kg", 1)]),
    ("Toz ürünler", [("Salep", "kg", 1), ("Chai tea latte", "kg", 1), ("Sıcak çikolata", "kg", 1), ("Çay", "adet", 1),
                     ("Matcha", "adet", 1), ("Ube", "adet", 1)]),
    ("Süt ve süt ürünleri", [("Yağlı süt", "litre", 12), ("Laktozsuz süt", "litre", 12), ("Badem sütü", "litre", 2),
                             ("Yulaf sütü", "litre", 3), ("Hindistan cevizi sütü", "litre", 2), ("Sprey krema", "adet", 3)]),
    ("Diğer içecekler", [("Su 500 cc", "adet", 12), ("Soda sade", "adet", 12), ("Soda limonlu", "adet", 12),
                         ("Capri-Sun", "adet", 3)]),
    ("Diğer yiyecekler", [("Belçika çikolatası", "adet", 1), ("Granola", "adet", 1), ("Granola glutensiz", "adet", 1),
                          ("Rulokat", "adet", 1), ("Lokum", "adet", 1)]),
    ("Paket", [("Kraft poşet", "adet", 100), ("Yumurtalık - viyol", "adet", 100), ("Tatlı kutusu", "adet", 150),
               ("Kese kağıdı", "adet", 100), ("Yağlı kağıt", "adet", 1), ("Tıpaç", "adet", 1), ("Granola kase", "adet", None)]),
    ("Sarf malzeme", [("Karton bardak 8 oz", "adet", 100), ("Karton bardak 12 oz", "adet", 100),
                      ("Soğuk bardak pet", "adet", 100), ("Kapak (sıcak)", "adet", 150), ("Kapak (soğuk)", "adet", 100),
                      ("Kapak soğuk pet", "paket", 3), ("Kapak soğuk pet bombe", "paket", 3), ("Pipet", "adet", 100),
                      ("Peçete büyük", "paket", 3), ("Peçete küçük", "paket", None), ("Islak mendil", "adet", 100),
                      ("Şeker", "adet", None), ("Sleeve büyük", "adet", 100), ("Sleeve küçük", "adet", 100),
                      ("Tahta karıştırıcı", "paket", 3)]),
    ("Temizlik malzemesi", [("Bulaşık deterjanı", "adet", 100), ("Tuvalet kağıdı", "adet", 150), ("Sıvı sabun", "adet", 100),
                            ("Domestos", "adet", 100), ("Yüzey temizleyici", "paket", 3)]),
]


def clean(text, limit):
    return " ".join((text or "").split())[:limit]


def parse_qty(raw):
    """'2,5' / '2.5' / ' 3 ' -> float; boş -> None; geçersiz -> ValueError."""
    raw = (raw or "").strip().replace(" ", "")
    if raw == "":
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", raw):      # 1.250,5 -> 1250.5
        raw = raw.replace(".", "")
    raw = raw.replace(",", ".")
    value = float(raw)
    if value < 0 or value > 1_000_000:
        raise ValueError("aralık dışı")
    return round(value, 3)


def fmt(value):
    """Türkçe sayı: 2.5 -> '2,5', 3.0 -> '3', None -> ''."""
    if value is None:
        return ""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def get_setting(user, create=False):
    setting = StockSetting.query.filter_by(user_id=user.id).first()
    if not setting and create:
        setting = StockSetting(user_id=user.id, token=new_token())
        db.session.add(setting)
        db.session.commit()
    return setting


def new_token():
    while True:
        token = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:10]
        if len(token) >= 8 and not StockSetting.query.filter_by(token=token).first():
            return token


def categories(user, with_inactive=False):
    cats = StockCategory.query.filter_by(user_id=user.id).order_by(StockCategory.sort, StockCategory.id).all()
    out = []
    for cat in cats:
        items = cat.items.all() if with_inactive else [i for i in cat.items.all() if i.is_active]
        out.append((cat, items))
    return out


def next_sort(model, **filters):
    last = db.session.query(db.func.max(model.sort)).filter_by(**filters).scalar()
    return (last or 0) + 10


def seed_default(user):
    """Örnek listeyi ekler; aynı adlı kategori/ürün varsa atlar. Eklenen ürün sayısını döndürür."""
    added = 0
    for cat_name, items in DEFAULT_LIST:
        added += add_items(user, cat_name, items)
    db.session.commit()
    return added


def add_items(user, cat_name, items):
    key = cat_name.casefold()
    cat = next((c for c in StockCategory.query.filter_by(user_id=user.id) if c.name.casefold() == key), None)
    if not cat:
        cat = StockCategory(user_id=user.id, name=cat_name, sort=next_sort(StockCategory, user_id=user.id))
        db.session.add(cat)
        db.session.flush()
    existing = {i.name.casefold() for i in cat.items.all()}
    added = 0
    for name, unit, min_stock in items:
        if not name or name.casefold() in existing:
            continue
        db.session.add(StockItem(user_id=user.id, category_id=cat.id, name=name, unit=unit or "adet",
                                 min_stock=min_stock, sort=next_sort(StockItem, category_id=cat.id) + added * 10))
        existing.add(name.casefold())
        added += 1
    return added


def import_xlsx(user, stream):
    """Excel'den ürün listesi: sütunlar Kategori, Ürün, Birim, Min. Stok (ilk sayfa, başlık satırı aranır)."""
    import openpyxl
    wb = openpyxl.load_workbook(stream, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:15]):
        names = [str(v or "").strip().lower() for v in row]
        if "ürün" in names or "urun" in names:
            header_idx = i
            for j, n in enumerate(names):
                if n.startswith("kategori"):
                    cols["cat"] = j
                elif n in ("ürün", "urun", "ürün adı"):
                    cols["name"] = j
                elif n.startswith("birim"):
                    cols["unit"] = j
                elif n.startswith("min"):
                    cols["min"] = j
            break
    if header_idx is None or "name" not in cols:
        raise ValueError("Başlık satırında 'Ürün' sütunu bulunamadı.")
    grouped, current = {}, "Genel"
    for row in rows[header_idx + 1:]:
        cell = lambda key: row[cols[key]] if key in cols and cols[key] < len(row) else None  # noqa: E731
        name = clean(str(cell("name") or ""), 80)
        cat = clean(str(cell("cat") or ""), 60)
        if not name:
            if cat:   # yalnız kategori başlığı satırı
                current = cat.title() if cat.isupper() else cat
            continue
        cat = cat or current
        unit = clean(str(cell("unit") or "adet"), 20).lower() or "adet"
        try:
            min_stock = float(str(cell("min")).replace(",", ".")) if cell("min") not in (None, "") else None
        except ValueError:
            min_stock = None
        grouped.setdefault(cat, []).append((name, unit, min_stock))
    added = sum(add_items(user, cat, items) for cat, items in grouped.items())
    db.session.commit()
    return added


def last_counted(user, before_count=None):
    """Her ürün için en son sayılan miktar: {item_id: (miktar, sayım tarihi)}."""
    q = (db.session.query(StockCountLine.item_id, StockCountLine.counted, StockCount.count_date, StockCount.id)
         .join(StockCount, StockCount.id == StockCountLine.count_id)
         .filter(StockCount.user_id == user.id, StockCountLine.counted.isnot(None), StockCountLine.item_id.isnot(None)))
    if before_count is not None:
        q = q.filter(db.or_(StockCount.count_date < before_count.count_date,
                            db.and_(StockCount.count_date == before_count.count_date, StockCount.id < before_count.id)))
    out = {}
    for item_id, counted, day, _cid in q.order_by(StockCount.count_date.desc(), StockCount.id.desc()).limit(5000):
        out.setdefault(item_id, (counted, day))
    return out


def save_count(user, counted_by, count_date, entries, note=""):
    """entries: {item_id: {"counted": float|None, "received": float|None, "note": str}}"""
    count = StockCount(user_id=user.id, counted_by=clean(counted_by, 60), count_date=count_date,
                       note=clean(note, 500) or None)
    db.session.add(count)
    db.session.flush()
    prev = last_counted(user, before_count=count)
    for cat, items in categories(user):
        for item in items:
            e = entries.get(item.id, {})
            db.session.add(StockCountLine(
                count_id=count.id, item_id=item.id, category_name=cat.name, item_name=item.name, unit=item.unit,
                min_stock=item.min_stock, prev_qty=prev.get(item.id, (None, None))[0],
                received=e.get("received"), counted=e.get("counted"), note=clean(e.get("note"), 200) or None))
    db.session.commit()
    return count


EDIT_WINDOW_HOURS = 12      # barista kendi sayımını bu süre içinde düzeltebilir


def can_staff_edit(count, now=None):
    now = now or datetime.utcnow()
    return bool(count.created_at) and now - count.created_at <= timedelta(hours=EDIT_WINDOW_HOURS)


def parse_entries(form, line_ids):
    """Düzeltme formu: c_/r_/n_<satır id>. Dönüş: (entries, errors)."""
    entries, errors = {}, {}
    for line_id in line_ids:
        entry = {}
        for key, field in (("counted", f"c_{line_id}"), ("received", f"r_{line_id}")):
            try:
                entry[key] = parse_qty(form.get(field))
            except ValueError:
                errors[field] = "Sayı yaz (ör. 2 ya da 2,5)."
        entry["note"] = form.get(f"n_{line_id}", "")
        entries[line_id] = entry
    return entries, errors


def refresh_prev(user_id):
    """Her sayımın "önceki" miktarlarını baştan hesaplar (eski bir sayım düzeltilince/silinince sonrakiler doğru kalsın)."""
    last = {}
    counts = StockCount.query.filter_by(user_id=user_id).order_by(StockCount.count_date, StockCount.id).all()
    for count in counts:
        lines = count.lines.all()
        for line in lines:
            if line.item_id:
                line.prev_qty = last.get(line.item_id, (None,))[0]
        for line in lines:
            if line.item_id and line.counted is not None:
                last[line.item_id] = (line.counted,)


def update_count(count, entries, editor, counted_by=None, count_date=None, note=None):
    """Kaydedilmiş sayımı düzeltir. Değişen satır sayısını döndürür."""
    changed = 0
    for line in count.lines.all():
        e = entries.get(line.id)
        if e is None:
            continue
        new_note = clean(e.get("note"), 200) or None
        if (line.counted, line.received, line.note) != (e.get("counted"), e.get("received"), new_note):
            line.counted, line.received, line.note = e.get("counted"), e.get("received"), new_note
            changed += 1
    if counted_by and len(clean(counted_by, 60)) >= 2:
        count.counted_by = clean(counted_by, 60)
    if count_date:
        count.count_date = count_date
    if note is not None:
        count.note = clean(note, 500) or None
    count.edited_at, count.edited_by = datetime.utcnow(), clean(editor, 60) or None
    db.session.flush()
    refresh_prev(count.user_id)
    db.session.commit()
    return changed


def summarize(count):
    lines = count.lines.all()
    counted = [l for l in lines if l.counted is not None]
    return {
        "total": len(lines),
        "counted": len(counted),
        "order": [l for l in lines if l.needs_order],
        "check": [l for l in counted if l.used is not None and l.used < 0],
        "notes": [l for l in lines if l.note],
        # önceki sayıma göre değişim: en çok azalan / artan önce
        "down": sorted([l for l in lines if l.diff is not None and l.diff < 0], key=lambda l: l.diff),
        "up": sorted([l for l in lines if l.diff is not None and l.diff > 0], key=lambda l: -l.diff),
        "same": len([l for l in lines if l.diff == 0]),
        "compared": len([l for l in lines if l.diff is not None]),
    }


def signed(value):
    """+1 / −1,5 / 0 biçiminde fark."""
    if value is None:
        return ""
    if value > 0:
        return "+" + fmt(value)
    if value < 0:
        return "−" + fmt(-value)
    return "0"


def grouped_lines(count):
    groups = []
    for line in count.lines.all():
        if not groups or groups[-1][0] != line.category_name:
            groups.append((line.category_name, []))
        groups[-1][1].append(line)
    return groups


def today_local():
    import pytz
    return datetime.now(pytz.timezone("Europe/Istanbul")).date()


def parse_day(raw):
    try:
        day = datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    return day if date(2020, 1, 1) <= day <= today_local() else None
