"""Haftalık Kâr Karnesi: bir kullanıcının belirli bir dönemdeki satış, komisyon,
ürün maliyeti ve ürün bazlı kârını hesaplar; Telegram mesajını üretir.

Kâr hesabı (operasyonel):
    ciro − platform komisyonu − ürün maliyeti − sipariş başı paket gideri − reklam gideri
Aylık sabit giderler (kira, personel) ve dönem toplamı sabit giderler karnede
yer almaz; bunlar Kârlılık ekranında ayrıca gösterilir.
"""
import json
from datetime import datetime, timedelta

import pytz

from extensions import db

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
LOSS_MIN_QUANTITY = 1  # bu adetten az satılan ürün zarar listesine girmez


def _norm(name: str) -> str:
    return " ".join((name or "").casefold().split())


def last_week_range(today=None):
    """Bir önceki Pazartesi–Pazar aralığı (Türkiye takvimi)."""
    today = today or datetime.now(TURKEY_TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday - timedelta(days=1)


def _utc_bounds(start_day, end_day):
    start = TURKEY_TZ.localize(datetime.combine(start_day, datetime.min.time()))
    end = TURKEY_TZ.localize(datetime.combine(end_day + timedelta(days=1), datetime.min.time()))
    return (start.astimezone(pytz.utc).replace(tzinfo=None),
            end.astimezone(pytz.utc).replace(tzinfo=None))


def compute(user_id: int, start_day, end_day) -> dict:
    """Dönem özetini hesaplar. Tarihler dahil (start_day..end_day)."""
    from models import (AdisyoConnection, AdisyoReport, DailyAdvertisingExpense, Integration,
                        Order, PlatformCommission, PlatformExpense, ProductCost)
    from routes.dashboard import (_cost_product_lines, _is_cancelled_order, _is_refunded_order,
                                  _parse_raw_json)

    since, until = _utc_bounds(start_day, end_day)
    costs = {_norm(r.product_name): r.unit_cost for r in ProductCost.query.filter_by(user_id=user_id).all()}
    rates = {r.platform: (r.percentage or 0) for r in PlatformCommission.query.filter_by(user_id=user_id).all()}
    per_order = [e for e in PlatformExpense.query.filter_by(user_id=user_id, expense_type="per_order").all()]

    platforms, products = {}, {}

    def platform_row(platform):
        return platforms.setdefault(platform, {"platform": platform, "orders": 0, "revenue": 0.0,
                                               "commission": 0.0, "cost": 0.0, "other": 0.0})

    def add_line(platform, name, quantity, revenue):
        rate = rates.get(platform, 0) / 100
        unit_cost = costs.get(_norm(name))
        prow = platform_row(platform)
        prow["revenue"] += revenue
        prow["commission"] += revenue * rate
        product = products.setdefault(_norm(name), {"name": name, "quantity": 0.0, "revenue": 0.0,
                                                    "commission": 0.0, "cost": 0.0, "has_cost": unit_cost is not None})
        product["quantity"] += quantity
        product["revenue"] += revenue
        product["commission"] += revenue * rate
        if unit_cost is not None:
            product["cost"] += quantity * unit_cost
            prow["cost"] += quantity * unit_cost

    orders = Order.query.filter(Order.user_id == user_id, Order.created_at >= since,
                                Order.created_at < until).all()
    for order in orders:
        if _is_cancelled_order(order) or _is_refunded_order(order):
            continue
        platform_row(order.platform)["orders"] += 1
        for line in _cost_product_lines(order.platform, _parse_raw_json(order.raw_json)):
            add_line(order.platform, line["name"], line["quantity"], line["revenue"])

    reports = (AdisyoReport.query.join(AdisyoConnection)
               .join(Integration, AdisyoConnection.integration_id == Integration.id)
               .filter(Integration.user_id == user_id, AdisyoReport.state == "ready",
                       AdisyoReport.day >= start_day, AdisyoReport.day <= end_day).all())
    for report in reports:
        try:
            summary = json.loads(report.summary_json or "{}")
        except (TypeError, ValueError):
            continue
        platform_row("adisyo")["orders"] += max(0, int(summary.get("count") or 0) - int(summary.get("cancelled") or 0))
        for item in summary.get("products", []):
            add_line("adisyo", str(item.get("name") or "Ürün").strip(),
                     float(item.get("quantity") or 0), float(item.get("amount") or 0))

    for expense in per_order:
        if expense.platform == "genel":
            for prow in platforms.values():
                prow["other"] += expense.amount * prow["orders"]
        elif expense.platform in platforms:
            platforms[expense.platform]["other"] += expense.amount * platforms[expense.platform]["orders"]

    advertising = sum(e.amount for e in DailyAdvertisingExpense.query.filter(
        DailyAdvertisingExpense.user_id == user_id,
        DailyAdvertisingExpense.day >= start_day, DailyAdvertisingExpense.day <= end_day).all())

    for prow in platforms.values():
        prow["profit"] = prow["revenue"] - prow["commission"] - prow["cost"] - prow["other"]
        prow["margin"] = prow["profit"] / prow["revenue"] * 100 if prow["revenue"] else 0

    product_rows = []
    for product in products.values():
        if product["has_cost"]:
            product["profit"] = product["revenue"] - product["commission"] - product["cost"]
            product["unit_profit"] = product["profit"] / product["quantity"] if product["quantity"] else 0
        else:
            product["profit"] = None
            product["unit_profit"] = None
        product_rows.append(product)

    costed = [p for p in product_rows if p["profit"] is not None]
    revenue = sum(p["revenue"] for p in platforms.values())
    commission = sum(p["commission"] for p in platforms.values())
    cost = sum(p["cost"] for p in platforms.values())
    other = sum(p["other"] for p in platforms.values())
    uncosted = [p for p in product_rows if p["profit"] is None]
    uncosted_revenue = sum(p["revenue"] for p in uncosted)
    profit = revenue - commission - cost - other - advertising
    return {
        "start": start_day, "end": end_day,
        "orders": sum(p["orders"] for p in platforms.values()),
        "revenue": revenue, "commission": commission, "cost": cost,
        "other": other, "advertising": advertising, "profit": profit,
        "margin": profit / revenue * 100 if revenue else 0,
        "platforms": sorted(platforms.values(), key=lambda p: -p["revenue"]),
        "top_products": sorted([p for p in costed if p["profit"] > 0], key=lambda p: -p["profit"])[:3],
        "loss_products": sorted([p for p in costed if p["profit"] < 0 and p["quantity"] >= LOSS_MIN_QUANTITY],
                                key=lambda p: p["profit"]),
        "uncosted_count": len(uncosted),
        "uncosted_revenue_share": uncosted_revenue / revenue * 100 if revenue else 0,
        "costs_complete": bool(product_rows) and not uncosted,
    }


def compute_with_previous(user_id: int, start_day, end_day) -> dict:
    current = compute(user_id, start_day, end_day)
    length = (end_day - start_day).days + 1
    previous = compute(user_id, start_day - timedelta(days=length), start_day - timedelta(days=1))
    current["previous"] = {"revenue": previous["revenue"], "profit": previous["profit"], "orders": previous["orders"]}
    current["revenue_change"] = _change(current["revenue"], previous["revenue"])
    current["profit_change"] = _change(current["profit"], previous["profit"]) if previous["revenue"] else None
    return current


def _change(now, before):
    if not before:
        return None
    return (now - before) / abs(before) * 100


def tl(value: float) -> str:
    """1234.5 → '1.234 TL' (Türkçe binlik ayırıcı, kuruşsuz)."""
    sign = "−" if value < 0 else ""
    return f"{sign}{abs(value):,.0f}".replace(",", ".") + " TL"


def _pct(change):
    if change is None:
        return ""
    arrow = "▲" if change >= 0 else "▼"
    return f" ({arrow} %{abs(change):.0f})"


def telegram_text(report: dict, platform_label, show_details: bool, panel_url: str) -> str:
    start, end = report["start"].strftime("%d.%m"), report["end"].strftime("%d.%m.%Y")
    lines = [f"📒 <b>Haftalık Kâr Karnesi</b> · {start}–{end}", ""]
    lines.append(f"🧾 Sipariş: <b>{report['orders']}</b>")
    lines.append(f"💰 Ciro: <b>{tl(report['revenue'])}</b>{_pct(report.get('revenue_change'))}")
    lines.append(f"🏷️ Komisyona giden: <b>{tl(report['commission'])}</b>")
    if report["cost"]:
        lines.append(f"🥘 Ürün maliyeti: {tl(report['cost'])}")
    if report["other"] or report["advertising"]:
        lines.append(f"📦 Paket + reklam: {tl(report['other'] + report['advertising'])}")
    lines.append(f"✅ Tahmini kâr: <b>{tl(report['profit'])}</b>{_pct(report.get('profit_change'))}")

    if len(report["platforms"]) > 1:
        lines += ["", "<b>Platformlar</b>"]
        for p in report["platforms"]:
            lines.append(f"• {platform_label(p['platform'])}: {tl(p['revenue'])} ciro · "
                         f"{tl(p['profit'])} kâr (%{p['margin']:.0f})")

    if report["top_products"]:
        lines += ["", "<b>En çok kazandıran</b>"]
        for p in report["top_products"]:
            lines.append(f"• {p['name']}: {tl(p['profit'])} ({p['quantity']:.0f} adet)")

    losses = report["loss_products"]
    if losses:
        lines.append("")
        if show_details:
            lines.append(f"⚠️ <b>Zararına satılan ürünler ({len(losses)})</b>")
            for p in losses[:5]:
                lines.append(f"• {p['name']}: adet başı {tl(p['unit_profit'])} · toplam {tl(p['profit'])}")
            if len(losses) > 5:
                lines.append(f"… ve {len(losses) - 5} ürün daha")
        else:
            lines.append(f"⚠️ <b>{len(losses)} ürün zararına satıldı.</b> Hangileri olduğunu Pro'da görebilirsin.")

    if report["uncosted_count"]:
        lines += ["", f"ℹ️ {report['uncosted_count']} ürünün maliyeti girilmemiş "
                      f"(cironun %{report['uncosted_revenue_share']:.0f}'i). Girersen kâr daha doğru hesaplanır."]

    lines += ["", f"Detay: {panel_url}",
              "<i>Kira, personel gibi aylık sabit giderler dahil değildir.</i>"]
    return "\n".join(lines)
