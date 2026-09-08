"""Read-only Adisyo reports. No webhook or order mutations."""
from collections import defaultdict
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
import unicodedata

import pytz
import requests
from flask import current_app

BASE_URL = "https://ext.adisyo.com/api/External/v2"
TURKEY_TZ = pytz.timezone("Europe/Istanbul")


class AdisyoError(ValueError):
    pass


def decimal(value):
    try:
        number = Decimal(str(value if value is not None else 0))
        if not number.is_finite():
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        raise AdisyoError("Adisyo sayisal veri formati gecersiz.") from None


def local_day(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Adisyo examples omit the offset; these are POS local times.
        if stamp.tzinfo is None:
            stamp = TURKEY_TZ.localize(stamp)
        return stamp.astimezone(TURKEY_TZ).date()
    except (ValueError, TypeError):
        raise AdisyoError("Adisyo siparis tarihi eksik veya gecersiz.") from None


def completed_page(connection, day, page):
    if not connection.api_key or not connection.api_secret:
        raise AdisyoError("Adisyo anahtarlari okunamadi; baglanti bilgilerini kontrol edin.")
    start = TURKEY_TZ.localize(datetime.combine(day, time.min)).astimezone(timezone.utc)
    try:
        response = requests.get(
            current_app.config.get("ADISYO_API_BASE", BASE_URL).rstrip("/") + "/CompletedOrders",
            headers={"x-api-key": connection.api_key, "x-api-secret": connection.api_secret,
                     "x-api-consumer": connection.consumer},
            params={"page": page, "startDate": start.strftime("%Y-%m-%d %H:%M:%S"),
                    "includeCancelled": "true", "orderType": "TakeAway,Table,Retail"},
            timeout=(5, 20), allow_redirects=False,
        )
    except requests.RequestException:
        raise AdisyoError("Adisyo baglantisi kurulamadi veya zaman asimina ugradi.") from None
    if response.status_code != 200:
        raise AdisyoError(f"Adisyo HTTP {response.status_code}; yetki veya istek limitini kontrol edin.")
    try:
        data = response.json()
    except ValueError:
        raise AdisyoError("Adisyo JSON yaniti gecersiz.") from None
    if not isinstance(data, dict) or str(data.get("status")) != "100":
        raise AdisyoError("Adisyo islemi basarisiz; API erisim yetkisini kontrol edin.")
    rows = data.get("orders")
    try:
        pages, total = int(data["pageCount"]), int(data["totalCount"])
    except (KeyError, ValueError, TypeError):
        raise AdisyoError("Adisyo sayfalama bilgisi eksik.") from None
    if not isinstance(rows, list) or pages < 0 or total < 0 or pages > 500:
        raise AdisyoError("Adisyo sayfalama yaniti gecersiz.")
    if total and (pages == 0 or (page <= pages and not rows)):
        raise AdisyoError("Adisyo eksik siparis sayfasi dondurdu.")
    return rows, max(pages, 1)


def normalize(order, day):
    if not isinstance(order, dict) or not order.get("id"):
        raise AdisyoError("Adisyo siparis kimligi eksik.")
    order_day = order.get("insertDate") or order.get("updateDate")
    if local_day(order_day) != day:
        return None
    status = "".join(c for c in unicodedata.normalize("NFKD", str(order.get("status", "")).casefold())
                     if not unicodedata.combining(c))
    cancelled = any(s in status for s in ("iptal", "cancel", "reject"))
    if not cancelled and order.get("statusId") != 7 and status not in ("kapandı", "kapandi", "closed"):
        raise AdisyoError("Taninmayan Adisyo tamamlanmis siparis durumu; rapor durduruldu.")
    if order.get("currency") != "TRY":
        raise AdisyoError("Rapor sadece TRY destekliyor; para birimi kontrol edilmeli.")
    products, payments = [], []
    if not isinstance(order.get("products"), list) or not isinstance(order.get("payments"), list):
        raise AdisyoError("Adisyo urun veya odeme listesi eksik.")
    for item in order["products"]:
        if item.get("cancelReason"):
            continue
        products.append({"key": str(item.get("productUnitId") or item.get("productId") or item["productName"]),
                         "name": str(item["productName"]), "child": bool(item.get("parentId")),
                         "quantity": str(decimal(item.get("quantity"))),
                         "amount": str(decimal(item.get("totalAmount")))})
    for payment in order["payments"]:
        if payment.get("currency") != "TRY":
            raise AdisyoError("Odeme para birimi TRY degil; rapor durduruldu.")
        payments.append({"name": str(payment.get("paymentName") or "Belirtilmemis"),
                         "amount": str(decimal(payment.get("amount")))})
    # Keep reporting data only, without customer addresses, phones or invoices.
    return {"id": str(order["id"]), "cancelled": cancelled,
            "amount": str(decimal(order.get("orderTotal"))),
            "discount": str(decimal(order.get("discountAmount"))),
            "tax": str(decimal(order.get("taxAmount"))),
            "products": products, "payments": payments}


def summarize(rows):
    result = {"count": 0, "cancelled": 0}
    amounts = defaultdict(Decimal)
    products, payments = {}, defaultdict(Decimal)
    for row in rows:
        amounts["gross_amount"] += decimal(row["amount"])
        if row["cancelled"]:
            result["cancelled"] += 1
            amounts["cancelled_amount"] += decimal(row["amount"])
            continue
        result["count"] += 1
        for name in ("amount", "discount", "tax"):
            amounts[name] += decimal(row[name])
        for item in row["products"]:
            key = (item["key"], item["name"], item["child"])
            target = products.setdefault(key, {"name": item["name"], "child": item["child"],
                                                "quantity": Decimal(0), "amount": Decimal(0)})
            target["quantity"] += decimal(item["quantity"])
            target["amount"] += decimal(item["amount"])
        for payment in row["payments"]:
            payments[payment["name"]] += decimal(payment["amount"])
    for name in ("amount", "gross_amount", "discount", "tax", "cancelled_amount"):
        result[name] = f"{amounts[name]:.2f}"
    result["products"] = [{**p, "quantity": format(p["quantity"], "f"), "amount": f"{p['amount']:.2f}"}
                          for p in sorted(products.values(), key=lambda p: (-p["quantity"], p["name"]))]
    result["payments"] = [{"name": name, "amount": f"{amount:.2f}"} for name, amount in sorted(payments.items())]
    return result
