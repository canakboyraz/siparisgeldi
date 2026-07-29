"""Gelen webhook'lar — Migros Yemek (Gourmet), push tabanlı.

Migros modeli: Secret key ENTEGRASYON FİRMASI bazında tektir; webhook URL'leri de
firma bazında tek settir ve restoranlardan ÖNCE Migros'a iletilir. Bu yüzden
gelen her sipariş aynı URL'lere düşer; doğru restorana (kullanıcıya) payload'daki
**store id** ile eşleştiririz.

Migros'a iletilecek 3 URL:
    /webhooks/migros/order-created
    /webhooks/migros/order-canceled
    /webhooks/migros/delivery-status

Güvenlik: Migros webhook'ları Basic Auth ile gelir (firma bazında tek kimlik →
MIGROS_WEBHOOK_USER/PASS). Migros başarısız yanıtta 10-20-30 sn ile 3 kez dener;
bu yüzden işleyemesek bile 200 dönüp gereksiz retry'ı önleriz.
"""
import json
import hmac
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from extensions import db
from models import Integration, Order, User
from integrations import migros, getir
from notifications.dispatcher import send_to_user

webhooks_bp = Blueprint("webhooks", __name__)


def _check_basic_auth() -> bool:
    user = current_app.config.get("MIGROS_WEBHOOK_USER", "")
    pw = current_app.config.get("MIGROS_WEBHOOK_PASS", "")
    if not user and not pw:
        return bool(current_app.debug or current_app.config.get("ENV") == "development")
    if not user or not pw:
        return False
    auth = request.authorization
    return bool(
        auth
        and hmac.compare_digest(auth.username or "", user)
        and hmac.compare_digest(auth.password or "", pw)
    )


def _check_getir_api_key() -> bool:
    expected = current_app.config.get("GETIR_WEBHOOK_API_KEY", "")
    if not expected:
        return bool(current_app.debug or current_app.config.get("ENV") == "development")
    sent = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or ""
    return hmac.compare_digest(str(sent), str(expected))


def _find_integration(store_id) -> Integration:
    if store_id is None:
        return None
    return Integration.query.filter_by(
        platform="migros", migros_store_id=str(store_id), is_active=True
    ).first()


def _find_getir_integration(payload: dict) -> Integration:
    secret_key = getir.restaurant_secret_key(payload)
    if secret_key:
        for intg in Integration.query.filter_by(platform="getir", is_active=True).all():
            if intg.getir_restaurant_secret_key and hmac.compare_digest(
                intg.getir_restaurant_secret_key, secret_key
            ):
                return intg

    restaurant_id = getir.restaurant_id(payload)
    if restaurant_id:
        return Integration.query.filter_by(
            platform="getir", getir_restaurant_id=str(restaurant_id), is_active=True
        ).first()
    return None


def _ok(note=None):
    body = {"ok": True}
    if note:
        body["note"] = note
    return jsonify(body), 200


# Getir Yemek webhook endpointleri

@webhooks_bp.route("/getir/order-created", methods=["POST"])
def getir_order_created():
    if not _check_getir_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    intg = _find_getir_integration(p)
    if not intg:
        print("[GETIR] order-created: eslesen restoran yok")
        return _ok("no matching restaurant")
    return _process_getir(intg, "created", p)


@webhooks_bp.route("/getir/order-canceled", methods=["POST"])
def getir_order_canceled():
    if not _check_getir_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    intg = _find_getir_integration(p)
    if not intg:
        print("[GETIR] order-canceled: eslesen restoran yok")
        return _ok("no matching restaurant")
    return _process_getir(intg, "canceled", p)


@webhooks_bp.route("/getir/courier-status", methods=["POST"])
def getir_courier_status():
    if not _check_getir_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    intg = _find_getir_integration(p)
    if not intg:
        return _ok("no matching restaurant")
    return _process_getir(intg, "courier", p)


@webhooks_bp.route("/getir/restaurant-status", methods=["POST"])
def getir_restaurant_status():
    if not _check_getir_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    intg = _find_getir_integration(p)
    if not intg:
        return _ok("no matching restaurant")
    return _process_getir(intg, "restaurant", p)


def _process_getir(intg, kind, payload):
    user = db.session.get(User, intg.user_id)
    try:
        if kind == "created":
            _handle_getir_created(intg, user, payload)
        elif kind == "canceled":
            _handle_getir_canceled(intg, user, payload)
        elif kind == "courier":
            _handle_getir_courier(intg, user, payload)
        elif kind == "restaurant":
            _handle_getir_restaurant(intg, user, payload)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        intg.last_error = str(e)[:300]
        db.session.commit()
        print(f"[GETIR WEBHOOK] Hata user={intg.user_id}: {e}")
        return _ok("error-logged")
    return _ok()


def _handle_getir_created(intg, user, payload):
    fields = getir.extract_order_fields(payload)
    if not fields["external_id"]:
        raise ValueError("Getir order id bulunamadi")
    existing = Order.query.filter_by(
        user_id=intg.user_id, platform="getir", external_id=fields["external_id"]
    ).first()
    if existing:
        existing.status = fields["status"] or existing.status
        existing.raw_json = json.dumps(payload, ensure_ascii=False)
        return

    order = Order(user_id=intg.user_id, platform="getir",
                  raw_json=json.dumps(payload, ensure_ascii=False), **fields)
    order.mark_status_notified("INITIAL")
    db.session.add(order)
    db.session.commit()
    if intg.notify_new_order:
        amount = f"{fields['total_price']:.2f} ₺"
        send_to_user(user, getir.format_order_created(payload),
                     wa=["Yeni sipariş · Getir Yemek", fields["order_number"],
                         getir.summarize_items(payload), amount])
        print(f"[GETIR] yeni siparis #{fields['order_number']} (user={intg.user_id})")


def _handle_getir_canceled(intg, user, payload):
    fields = getir.extract_order_fields(payload)
    ext_id = fields["external_id"]
    order = Order.query.filter_by(
        user_id=intg.user_id, platform="getir", external_id=ext_id
    ).first() if ext_id else None

    original_payload = None
    if order:
        try:
            original_payload = json.loads(order.raw_json) if order.raw_json else None
        except (TypeError, ValueError):
            original_payload = None
        order.status = fields["status"] if fields["status"] in ("AdminCancelled", "AutoCancelled") else "Cancelled"
        order.raw_json = json.dumps(payload, ensure_ascii=False)
        order.mark_status_notified(order.status)
        db.session.commit()
    elif ext_id:
        fields["status"] = fields["status"] if fields["status"] in ("AdminCancelled", "AutoCancelled") else "Cancelled"
        order = Order(user_id=intg.user_id, platform="getir",
                      raw_json=json.dumps(payload, ensure_ascii=False), **fields)
        order.mark_status_notified(order.status)
        db.session.add(order)
        db.session.commit()

    if intg.notify_cancel:
        amount = f"{(order.total_price if order else fields['total_price']):.2f} ₺"
        items = getir.summarize_items(original_payload or payload)
        send_to_user(user, getir.format_order_canceled(payload, original_payload),
                     wa=["Sipariş iptal · Getir Yemek", fields["order_number"] or ext_id or "-",
                         items, amount])
        print(f"[GETIR] iptal #{fields['order_number'] or ext_id} (user={intg.user_id})")


def _handle_getir_courier(intg, user, payload):
    ext_id = getir.order_id(payload)
    order = Order.query.filter_by(
        user_id=intg.user_id, platform="getir", external_id=ext_id
    ).first() if ext_id else None
    if order:
        pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {}
        pickup_min = pickup.get("min") or ""
        pickup_max = pickup.get("max") or ""
        pickup_range = f"{pickup_min}-{pickup_max}" if (pickup_min or pickup_max) else ""
        status_key = f"COURIER:{payload.get('courierStatus') or payload.get('status') or pickup_range or 'updated'}"
        if order.is_status_notified(status_key):
            return
        order.mark_status_notified(status_key)
        db.session.commit()
    if intg.notify_status_change:
        send_to_user(user, getir.format_courier_status(payload),
                     wa=["Kurye durumu · Getir Yemek", getir.order_number(payload) or ext_id or "-",
                         "-", "-"])


def _handle_getir_restaurant(intg, user, payload):
    if intg.getir_restaurant_name is None:
        intg.getir_restaurant_name = getir.restaurant_name(payload) or intg.getir_restaurant_name
    if intg.notify_status_change:
        send_to_user(user, getir.format_restaurant_status(payload),
                     wa=["Restoran durumu · Getir Yemek",
                         getir.restaurant_name(payload) or getir.restaurant_id(payload) or "-",
                         "-", "-"])


# ── Migros'un çağıracağı 3 endpoint ─────────────────────────────────────────

@webhooks_bp.route("/migros/order-created", methods=["POST"])
def migros_order_created():
    if not _check_basic_auth():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    store_id = (p.get("store") or {}).get("id")
    intg = _find_integration(store_id)
    if not intg:
        print(f"[MIGROS] order-created: eşleşen restoran yok (store={store_id})")
        return _ok("no matching store")
    return _process(intg, "created", p)


@webhooks_bp.route("/migros/order-canceled", methods=["POST"])
def migros_order_canceled():
    if not _check_basic_auth():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    store_id = p.get("StoreId") or p.get("storeId")
    intg = _find_integration(store_id)
    if not intg:
        return _ok("no matching store")
    return _process(intg, "canceled", p)


@webhooks_bp.route("/migros/delivery-status", methods=["POST"])
def migros_delivery_status():
    if not _check_basic_auth():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    intg = _find_integration(p.get("storeId"))
    if not intg:
        return _ok("no matching store")
    return _process(intg, "delivery", p)


# Migros tek URL kullanırsa diye: şekle göre otomatik ayır
@webhooks_bp.route("/migros", methods=["POST"])
def migros_any():
    if not _check_basic_auth():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    p = request.get_json(silent=True) or {}
    wtype = migros.detect_webhook_type(p)
    if wtype == migros.WEBHOOK_ORDER_CREATED:
        store_id = (p.get("store") or {}).get("id")
        kind = "created"
    elif wtype == migros.WEBHOOK_ORDER_CANCELED:
        store_id = p.get("StoreId") or p.get("storeId")
        kind = "canceled"
    elif wtype == migros.WEBHOOK_DELIVERY_STATUS:
        store_id = p.get("storeId")
        kind = "delivery"
    else:
        return _ok("ignored")
    intg = _find_integration(store_id)
    if not intg:
        return _ok("no matching store")
    return _process(intg, kind, p)


# ── Ortak işleyici ──────────────────────────────────────────────────────────

def _process(intg, kind, payload):
    user = db.session.get(User, intg.user_id)
    try:
        if kind == "created":
            _handle_created(intg, user, payload)
        elif kind == "canceled":
            _handle_canceled(intg, user, payload)
        elif kind == "delivery":
            _handle_delivery(intg, user, payload)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        intg.last_error = str(e)[:300]
        db.session.commit()
        print(f"[MIGROS WEBHOOK] Hata user={intg.user_id}: {e}")
        return _ok("error-logged")  # 200 → Migros gereksiz retry yapmasın
    return _ok()


def _handle_created(intg, user, payload):
    fields = migros.extract_order_fields(payload)
    existing = Order.query.filter_by(
        user_id=intg.user_id, platform="migros", external_id=fields["external_id"]
    ).first()
    if existing:
        return
    order = Order(user_id=intg.user_id, platform="migros",
                  raw_json=json.dumps(payload, ensure_ascii=False), **fields)
    order.mark_status_notified("INITIAL")
    db.session.add(order)
    db.session.commit()
    if intg.notify_new_order:
        amount = f"{fields['total_price']:.2f} ₺"
        send_to_user(user, migros.format_order_created(payload),
                     wa=["Yeni sipariş · Migros Yemek", fields["order_number"],
                         migros.summarize_items(payload), amount])
        print(f"[MIGROS] 🆕 #{fields['order_number']} (user={intg.user_id})")


def _handle_canceled(intg, user, payload):
    ext_id = str(payload.get("OrderId") or payload.get("orderId") or "")
    order = Order.query.filter_by(
        user_id=intg.user_id, platform="migros", external_id=ext_id
    ).first()
    original_payload = None
    if order:
        try:
            original_payload = json.loads(order.raw_json) if order.raw_json else None
        except (TypeError, ValueError):
            original_payload = None
        order.status = "Cancelled"
        if not order.is_status_notified("Cancelled"):
            order.mark_status_notified("Cancelled")
        db.session.commit()
    if intg.notify_cancel:
        amount = f"{order.total_price:.2f} ₺" if order else "-"
        items = migros.summarize_items(original_payload) if original_payload else "-"
        send_to_user(user, migros.format_order_canceled(payload, original_payload),
                     wa=["Sipariş iptal · Migros Yemek", ext_id or "-", items, amount])
        print(f"[MIGROS] ❌ iptal #{ext_id} (user={intg.user_id})")


def _handle_delivery(intg, user, payload):
    ext_id = str(payload.get("orderId") or "")
    ds = payload.get("deliveryStatus", "")
    order = Order.query.filter_by(
        user_id=intg.user_id, platform="migros", external_id=ext_id
    ).first()
    if order:
        order.status = payload.get("status") or order.status
        if ds and order.is_status_notified(ds):
            return
        if ds:
            order.mark_status_notified(ds)
        db.session.commit()
    if intg.notify_status_change:
        title = migros._DELIVERY_MAP.get(ds, ("", "Kurye durumu", ""))[1]
        send_to_user(user, migros.format_delivery_status(payload),
                     wa=[f"{title} · Migros Yemek", ext_id or "-", "-", "-"])
        print(f"[MIGROS] 🚚 {ds} #{ext_id} (user={intg.user_id})")
