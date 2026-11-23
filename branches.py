"""Çok şubeli işletme: merkez hesap şubelerin satışını ve kârını tek yerde görür.

Her şube kendi SiparişGeldi hesabında çalışmaya devam eder (siparişler, maliyetler,
bildirimler). Merkez, davetle bağlanan şubelerin dönem özetini profit_report.compute
ile ayrı ayrı hesaplar ve toplar.
"""
from datetime import datetime, timedelta

import pytz

import profit_report
from extensions import db

TURKEY_TZ = pytz.timezone("Europe/Istanbul")

PERIODS = [("bugun", "Bugün"), ("dun", "Dün"), ("7gun", "Son 7 gün"), ("bu-ay", "Bu ay"), ("gecen-ay", "Geçen ay")]


def period_range(key: str, today=None):
    today = today or datetime.now(TURKEY_TZ).date()
    if key == "dun":
        return today - timedelta(days=1), today - timedelta(days=1)
    if key == "7gun":
        return today - timedelta(days=6), today
    if key == "bu-ay":
        return today.replace(day=1), today
    if key == "gecen-ay":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    return today, today


def group_for_owner(user_id):
    from models import BranchGroup
    return BranchGroup.query.filter_by(owner_id=user_id).first()


def ensure_group(user):
    from models import BranchGroup
    group = group_for_owner(user.id)
    if not group:
        group = BranchGroup(owner_id=user.id, owner_label=user.name)
        db.session.add(group)
        db.session.flush()
    return group


def membership(user_id):
    """Kullanıcının şube olarak bağlı olduğu merkez bağlantısı (varsa)."""
    from models import BranchLink
    return BranchLink.query.filter_by(branch_id=user_id, status="active").first()


def pending_invites(email):
    from models import BranchLink
    if not email:
        return []
    return BranchLink.query.filter(db.func.lower(BranchLink.email) == email.strip().lower(),
                                   BranchLink.status == "pending").all()


def members(group):
    """Toplama giren hesaplar: [(user, şube adı)] — merkezin kendisi dahil (ayarlıysa)."""
    from models import User
    out = []
    if group.include_owner:
        owner = db.session.get(User, group.owner_id)
        if owner:
            out.append((owner, group.owner_label or owner.name or "Merkez"))
    for link in sorted(group.links, key=lambda l: (l.label or l.email).casefold()):
        if link.status == "active" and link.branch_id:
            user = db.session.get(User, link.branch_id)
            if user:
                out.append((user, link.label or user.name or link.email))
    return out


def is_paid(user) -> bool:
    """Her şube ayrı Pro abonelik ister (şube başı aylık ücret)."""
    return bool(getattr(user, "is_pro_active", False))


def summary(group, start_day, end_day) -> dict:
    """Şube şube ve toplam: sipariş, ciro, komisyon, maliyet, gider, kâr; platform ve ürün toplamları.
    Aboneliği aktif olmayan şube toplama girmez, 'abonelik gerekli' olarak listelenir."""
    rows, platforms, products = [], {}, {}
    for user, label in members(group):
        if not is_paid(user):
            rows.append({"user_id": user.id, "label": label, "error": "Abonelik gerekli", "unpaid": True})
            continue
        try:
            rep = profit_report.compute(user.id, start_day, end_day)
        except Exception as e:  # tek şubenin hatası toplamı düşürmesin
            rows.append({"user_id": user.id, "label": label, "error": str(e)[:160]})
            continue
        rows.append({"user_id": user.id, "label": label, "orders": rep["orders"], "revenue": rep["revenue"],
                     "commission": rep["commission"], "cost": rep["cost"],
                     "other": rep["other"] + rep["advertising"], "profit": rep["profit"], "margin": rep["margin"],
                     "uncosted": rep["uncosted_count"], "uncosted_share": rep["uncosted_revenue_share"]})
        for p in rep["platforms"]:
            t = platforms.setdefault(p["platform"], {"platform": p["platform"], "orders": 0, "revenue": 0.0, "profit": 0.0})
            t["orders"] += p["orders"]
            t["revenue"] += p["revenue"]
            t["profit"] += p["profit"]
        for p in rep["all_products"]:
            key = profit_report._norm(p["name"])
            t = products.setdefault(key, {"name": p["name"], "quantity": 0.0, "revenue": 0.0, "branches": set()})
            t["quantity"] += p["quantity"]
            t["revenue"] += p["revenue"]
            t["branches"].add(label)
    ok = [r for r in rows if "error" not in r]
    total = {k: sum(r[k] for r in ok) for k in ("orders", "revenue", "commission", "cost", "other", "profit", "uncosted")}
    total["margin"] = total["profit"] / total["revenue"] * 100 if total["revenue"] else 0
    for r in ok:
        r["share"] = r["revenue"] / total["revenue"] * 100 if total["revenue"] else 0
    for p in platforms.values():
        p["margin"] = p["profit"] / p["revenue"] * 100 if p["revenue"] else 0
    top = sorted(products.values(), key=lambda p: -p["revenue"])[:10]
    for p in top:
        p["branches"] = len(p["branches"])
    return {"start": start_day, "end": end_day,
            "rows": sorted(ok, key=lambda r: -r["revenue"]) + [r for r in rows if "error" in r],
            "total": total, "platforms": sorted(platforms.values(), key=lambda p: -p["revenue"]),
            "top_products": top, "branch_count": len(ok), "unpaid": [r for r in rows if r.get("unpaid")]}


def daily_text(data: dict, panel_url: str) -> str:
    tl = profit_report.tl
    t = data["total"]
    day = data["start"].strftime("%d.%m.%Y")
    lines = [f"🏢 <b>Şubeler · Gün Sonu</b> · {day}", "",
             f"🧾 Sipariş: <b>{t['orders']}</b> · {data['branch_count']} şube",
             f"💰 Ciro: <b>{tl(t['revenue'])}</b>",
             f"✅ Tahmini kâr: <b>{tl(t['profit'])}</b> (%{t['margin']:.0f})", "", "<b>Şubeler</b>"]
    for r in data["rows"]:
        if r.get("unpaid"):
            lines.append(f"• {r['label']}: abonelik bitmiş, toplama dahil değil")
        elif "error" in r:
            lines.append(f"• {r['label']}: hesaplanamadı")
        elif r["orders"] == 0:
            lines.append(f"• {r['label']}: sipariş yok")
        else:
            lines.append(f"• {r['label']}: {tl(r['revenue'])} · {r['orders']} sipariş · kâr {tl(r['profit'])}")
    if len(data["platforms"]) > 1:
        lines += ["", "<b>Platformlar</b>"]
        from utils import platform_label
        for p in data["platforms"]:
            lines.append(f"• {platform_label(p['platform'])}: {tl(p['revenue'])} · {p['orders']} sipariş")
    if t["uncosted"]:
        lines += ["", "ℹ️ Bazı şubelerde maliyeti girilmemiş ürün var; kâr eksik hesaplanmış olabilir."]
    lines += ["", f"Detay: {panel_url}", "<i>Kira, personel gibi aylık sabit giderler dahil değildir.</i>"]
    return "\n".join(lines)


def daily_wa(data: dict) -> list:
    """WhatsApp rapor şablonu: {{1}} başlık+dönem {{2}} şubeler {{3}} ciro."""
    tl = profit_report.tl
    t = data["total"]
    parts = [f"{r['label']}: {tl(r['revenue'])} (kâr {tl(r['profit'])})" for r in data["rows"] if "error" not in r]
    return [f"Gün sonu · Tüm şubeler · {data['start'].strftime('%d.%m.%Y')} · {t['orders']} sipariş",
            (" | ".join(parts) or "Sipariş yok")[:400],
            f"{tl(t['revenue'])} · kâr {tl(t['profit'])}"]


def copy_costs(owner_id: int, branch_ids: list, overwrite: bool = False) -> dict:
    """Merkezin ürün maliyetlerini şubelere kopyalar. Varsayılan: yalnız şubede olmayanlar."""
    from models import ProductCost
    source = ProductCost.query.filter_by(user_id=owner_id).all()
    result = {}
    for bid in branch_ids:
        existing = {(c.platform, c.product_key): c for c in ProductCost.query.filter_by(user_id=bid).all()}
        n = 0
        for c in source:
            row = existing.get((c.platform, c.product_key))
            if row and not overwrite:
                continue
            if not row:
                row = ProductCost(user_id=bid, platform=c.platform, product_key=c.product_key)
                db.session.add(row)
            row.product_name, row.unit_cost = c.product_name, c.unit_cost
            n += 1
        result[bid] = n
    db.session.commit()
    return result


def send_daily_summaries(app):
    """Her gece: şube grubu olan merkezlere günün toplam özeti (tek mesaj)."""
    from flask import current_app
    from models import BranchGroup, User
    from notifications.dispatcher import send_to_user
    with app.app_context():
        today = datetime.now(TURKEY_TZ).date()
        domain = (current_app.config.get("APP_DOMAIN") or "siparisgeldi.net").removeprefix("https://").rstrip("/")
        for group in BranchGroup.query.filter_by(daily_summary=True).all():
            if not any(l.status == "active" for l in group.links):
                continue
            try:
                owner = db.session.get(User, group.owner_id)
                data = summary(group, today, today)
                send_to_user(owner, daily_text(data, f"https://{domain}/panel/subeler"), wa=daily_wa(data),
                             wa_template=current_app.config.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_raporr"),
                             source="subeler")
            except Exception as e:
                print(f"[ŞUBELER] Günlük özet hata owner={group.owner_id}: {e}")
