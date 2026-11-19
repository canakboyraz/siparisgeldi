"""Menü mühendisliği ve günlük hazırlık (talep) tahmini.

Menü mühendisliği (Kasavana & Smith yaklaşımı):
    popülerlik eşiği = ortalama ürün adedinin %70'i
    kârlılık eşiği   = adet ağırlıklı ortalama birim kâr (komisyon ve ürün maliyeti sonrası)
    Yıldız   : popüler + kârlı      → koru, öne çıkar
    Beygir   : popüler + az kârlı   → maliyet/porsiyon veya küçük fiyat ayarı
    Bilmece  : az satan + kârlı     → görünürlüğü artır
    Zayıf    : az satan + az kârlı  → yeniden fiyatla veya menüden çıkar

Hazırlık tahmini (hedef gün D):
    temel  = D-7 (geçen haftanın aynı günü) ürün adedi
    eğilim = dünün (D-1) toplam adedi / geçen haftanın aynı günündeki (D-8) toplam adet
             (0,7 – 1,3 arasıyla sınırlanır; mağaza geneli, ürün bazındaki gürültüyü azaltır)
    öneri  = yukarı yuvarla(temel × eğilim); geçen hafta satılmayıp dün satılan ürün için dünkü adet
"""
import math
from datetime import timedelta

import profit_report

CLASSES = {
    "star": {"label": "Yıldız", "icon": "⭐", "tip": "Hem çok satıyor hem kârlı. Menüde öne çıkar, kalitesini koru; küçük bir fiyat artışını kaldırabilir."},
    "horse": {"label": "Beygir", "icon": "🐴", "tip": "Çok satıyor ama birim kârı düşük. Maliyeti/porsiyonu gözden geçir, küçük fiyat artışı dene ya da kârlı bir ürünle menü yap."},
    "puzzle": {"label": "Bilmece", "icon": "🧩", "tip": "Kârlı ama az satıyor. Fotoğraf/açıklamayı güçlendir, menüde üste taşı, kampanya ya da tavsiye ile görünür kıl."},
    "dog": {"label": "Zayıf", "icon": "⚠️", "tip": "Hem az satıyor hem az kâr bırakıyor. Yeniden fiyatla, tarifini değiştir ya da menüden çıkarmayı düşün."},
}


def engineering(user_id, start_day, end_day):
    report = profit_report.compute(user_id, start_day, end_day)
    products = [p for p in _all_products(report) if p.get("profit") is not None and p["quantity"] > 0]
    uncosted = [p for p in _all_products(report) if p.get("profit") is None and p["quantity"] > 0]
    result = {"start": start_day, "end": end_day, "items": [], "groups": {k: [] for k in CLASSES},
              "uncosted": sorted(uncosted, key=lambda p: -p["quantity"]), "classes": CLASSES,
              "pop_threshold": 0, "margin_threshold": 0, "total_qty": 0, "total_profit": 0}
    if not products:
        return result
    total_qty = sum(p["quantity"] for p in products)
    total_profit = sum(p["profit"] for p in products)
    pop_threshold = 0.7 * total_qty / len(products)
    margin_threshold = total_profit / total_qty if total_qty else 0
    for p in products:
        unit = p["profit"] / p["quantity"]
        popular = p["quantity"] >= pop_threshold
        profitable = unit >= margin_threshold
        cls = "star" if popular and profitable else "horse" if popular else "puzzle" if profitable else "dog"
        item = {"name": p["name"], "quantity": p["quantity"], "revenue": p["revenue"], "profit": p["profit"],
                "unit_profit": unit, "unit_price": p["revenue"] / p["quantity"], "share": p["quantity"] / total_qty * 100,
                "class": cls}
        result["items"].append(item)
        result["groups"][cls].append(item)
    for cls, items in result["groups"].items():
        items.sort(key=lambda i: -i["profit"] if cls in ("star", "puzzle") else -i["quantity"] if cls == "horse" else i["profit"])
    result.update(pop_threshold=pop_threshold, margin_threshold=margin_threshold,
                  total_qty=total_qty, total_profit=total_profit)
    return result


def _all_products(report):
    """compute() yalnız seçili listeleri döndürür; tüm ürünleri ayrıca hesapla."""
    return report.get("all_products") or []


def _day_qty(user_id, day):
    report = profit_report.compute(user_id, day, day)
    return {profit_report._norm(p["name"]): p for p in report.get("all_products") or []}


def forecast(user_id, target_day):
    same_last_week = _day_qty(user_id, target_day - timedelta(days=7))
    yesterday = _day_qty(user_id, target_day - timedelta(days=1))
    yesterday_last_week = _day_qty(user_id, target_day - timedelta(days=8))
    y_total = sum(p["quantity"] for p in yesterday.values())
    ylw_total = sum(p["quantity"] for p in yesterday_last_week.values())
    raw_trend = (y_total / ylw_total) if ylw_total else 1.0
    trend = min(1.3, max(0.7, raw_trend)) if ylw_total and y_total else 1.0
    rows = []
    for key in set(same_last_week) | set(yesterday):
        base = same_last_week.get(key, {}).get("quantity", 0)
        yday = yesterday.get(key, {}).get("quantity", 0)
        name = (same_last_week.get(key) or yesterday.get(key))["name"]
        suggestion = math.ceil(base * trend) if base else math.ceil(yday)
        rows.append({"name": name, "last_week": base, "yesterday": yday, "suggestion": suggestion,
                     "delta": yday - base})
    rows.sort(key=lambda r: (-r["suggestion"], r["name"].casefold()))
    return {"target": target_day, "rows": rows, "trend": trend, "raw_trend": raw_trend,
            "yesterday_total": y_total, "yesterday_last_week_total": ylw_total,
            "last_week_total": sum(p["quantity"] for p in same_last_week.values()),
            "days": {"last_week": target_day - timedelta(days=7), "yesterday": target_day - timedelta(days=1),
                     "yesterday_last_week": target_day - timedelta(days=8)}}
