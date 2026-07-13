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
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from extensions import db
from models import Integration, Order, User
from integrations import migros
from notifications.dispatcher import send_to_user

webhooks_bp = Blueprint("webhooks", __name__)


def _check_basic_auth() -> bool:
    user = current_app.config.get("MIGROS_WEBHOOK_USER", "")
    pw   = current_app.config.get("MIGROS_WEBHOOK_PASS", "")
    if not user and not pw:
        return True  # kimlik tanımlı değilse doğrulamayı atla (dev)
    auth = request.authorization
    return bool(auth and auth.username == user and auth.password == pw)


def _find_integration(store_id) -> Integration:
    if store_id is None:
        return None
    return Integration.query.filter_by(
        platform="migros", migros_store_id=str(store_id), is_active=True
    ).first()


def _ok(note=None):
    body = {"ok": True}
    if note:
        body["note"] = note
    return jsonify(body), 200


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
        send_to_user(user, migros.format_order_created(payload))
        print(f"[MIGROS] 🆕 #{fields['order_number']} (user={intg.user_id})")


def _handle_canceled(intg, user, payload):
    ext_id = str(payload.get("OrderId") or payload.get("orderId") or "")
    order = Order.query.filter_by(
        user_id=intg.user_id, platform="migros", external_id=ext_id
    ).first()
    if order:
        order.status = "Cancelled"
        if not order.is_status_notified("Cancelled"):
            order.mark_status_notified("Cancelled")
        db.session.commit()
    if intg.notify_cancel:
        send_to_user(user, migros.format_order_canceled(payload))
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
        send_to_user(user, migros.format_delivery_status(payload))
        print(f"[MIGROS] 🚚 {ds} #{ext_id} (user={intg.user_id})")
