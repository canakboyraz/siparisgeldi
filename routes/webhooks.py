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
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from extensions import db
from models import Integration, Order, User
from integrations import migros, getir, trendyol_marketplace as tmp, yemeksepeti as ys
from notifications.dispatcher import send_to_user
from notifications import whatsapp as whatsapp_client
from utils import status_label

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


def _check_tmp_api_key() -> bool:
    expected = current_app.config.get("TRENDYOL_MARKETPLACE_WEBHOOK_API_KEY", "")
    if not expected:
        return bool(current_app.debug or current_app.config.get("ENV") == "development")
    sent = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or ""
    return hmac.compare_digest(str(sent), str(expected))


def _check_yemeksepeti_token() -> bool:
    expected = current_app.config.get("YEMEKSEPETI_WEBHOOK_TOKEN", "")
    if not expected:
        return bool(current_app.debug or current_app.config.get("ENV") == "development")
    sent = (
        request.headers.get("X-Webhook-Key")
        or request.headers.get("X-API-Key")
        or request.headers.get("x-api-key")
        or ""
    )
    if not sent:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            sent = authorization[7:].strip()
        else:
            sent = authorization.strip()
    return hmac.compare_digest(str(sent), str(expected))


def _check_whatsapp_signature() -> bool:
    app_secret = current_app.config.get("WHATSAPP_APP_SECRET", "")
    if not app_secret:
        return bool(current_app.debug or current_app.config.get("ENV") == "development")
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    digest = hmac.new(
        app_secret.encode("utf-8"),
        request.get_data(cache=True),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature[7:], digest)


def _whatsapp_status_error(status: dict) -> str:
    errors = status.get("errors") or []
    if not isinstance(errors, list):
        return str(errors)[:300]
    parts = []
    for error in errors[:2]:
        if not isinstance(error, dict):
            parts.append(str(error))
            continue
        code = error.get("code")
        title = error.get("title") or error.get("message")
        details = (error.get("error_data") or {}).get("details") if isinstance(error.get("error_data"), dict) else ""
        text = " - ".join(str(value) for value in (code, title, details) if value)
        if text:
            parts.append(text)
    return " | ".join(parts)[:300]


def _find_whatsapp_users(recipient_id: str) -> list:
    normalized = whatsapp_client._normalize_msisdn(recipient_id)
    if not normalized:
        return []
    users = User.query.filter(User.whatsapp_number.isnot(None)).all()
    return [
        user for user in users
        if whatsapp_client._normalize_msisdn(user.whatsapp_number) == normalized
    ]


@webhooks_bp.route("/whatsapp", methods=["GET", "POST"])
def whatsapp_status_webhook():
    """Meta WhatsApp Cloud API doğrulama ve teslimat durum webhook'u."""
    if request.method == "GET":
        mode = request.args.get("hub.mode", "")
        verify_token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        expected = current_app.config.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
        if expected and mode == "subscribe" and hmac.compare_digest(verify_token, expected):
            return challenge, 200, {"Content-Type": "text/plain"}
        return jsonify({"ok": False, "error": "verification failed"}), 403

    if not _check_whatsapp_signature():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    processed = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for status in value.get("statuses") or []:
                if not isinstance(status, dict):
                    continue
                message_id = str(status.get("id") or "")
                recipient_id = str(status.get("recipient_id") or "")
                users = []
                if message_id:
                    users = User.query.filter(User.whatsapp_last_message_id == message_id).all()
                if not users and recipient_id:
                    users = _find_whatsapp_users(recipient_id)
                if not users:
                    print(
                        f"[WHATSAPP DURUM] eşleşen kullanıcı yok "
                        f"status={status.get('status')} message_id={message_id or '-'}"
                    )
                    continue
                status_name = str(status.get("status") or "unknown").lower()[:30]
                status_error = _whatsapp_status_error(status)
                for user in users:
                    user.whatsapp_last_status = status_name
                    user.whatsapp_last_status_at = datetime.utcnow()
                    if message_id:
                        user.whatsapp_last_message_id = message_id[:200]
                    user.whatsapp_last_error = status_error or None
                    print(
                        f"[WHATSAPP DURUM] user={user.id} status={status_name} "
                        f"message_id={message_id or '-'}"
                        + (f" error={status_error}" if status_error else "")
                    )
                processed += len(users)
    db.session.commit()
    return _ok(f"processed={processed}")


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


@webhooks_bp.route("/marketplace/order", methods=["POST"])
def trendyol_marketplace_order():
    if not _check_tmp_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    orders = payload.get("content") if isinstance(payload.get("content"), list) else None
    if orders is None:
        orders = [payload]
    processed = 0
    for order_data in orders:
        if not isinstance(order_data, dict):
            continue
        supplier_id = str(order_data.get("supplierId") or "").strip()
        if not supplier_id:
            continue
        intg = Integration.query.filter_by(
            platform=tmp.PLATFORM, tmp_supplier_id=supplier_id, is_active=True
        ).first()
        if not intg:
            continue
        try:
            _handle_tmp_order(intg, order_data)
            processed += 1
        except Exception as e:
            db.session.rollback()
            intg.last_error = str(e)[:300]
            db.session.commit()
            print(f"[TMP WEBHOOK] Hata user={intg.user_id}: {e}")
    return _ok(f"processed={processed}")


def _handle_tmp_order(intg, order_data):
    fields = tmp.extract_order_fields(order_data)
    if not fields["external_id"]:
        raise ValueError("Trendyol Pazaryeri paket id bulunamadi")
    user = db.session.get(User, intg.user_id)
    existing = Order.query.filter_by(
        user_id=intg.user_id, platform=tmp.PLATFORM, external_id=fields["external_id"]
    ).first()
    if not existing:
        order = Order(
            user_id=intg.user_id,
            platform=tmp.PLATFORM,
            raw_json=json.dumps(order_data, ensure_ascii=False),
            **fields,
        )
        order.mark_status_notified("INITIAL")
        db.session.add(order)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        if intg.notify_new_order:
            send_to_user(
                user,
                tmp.format_new_order_message(order_data),
                wa=[
                    "Yeni pazaryeri siparişi · Trendyol",
                    fields["order_number"],
                    tmp.whatsapp_items_summary(order_data),
                    f"{fields['total_price']:.2f} ₺",
                ],
            )
        return

    current_status = fields["status"]
    status_changed = existing.status != current_status
    existing.status = current_status
    existing.order_number = fields["order_number"] or existing.order_number
    existing.total_price = fields["total_price"]
    existing.payment_type = fields["payment_type"]
    existing.customer_note = fields["customer_note"]
    existing.raw_json = json.dumps(order_data, ensure_ascii=False)
    intg.last_sync_at = datetime.utcnow()
    intg.last_error = None

    should_notify = status_changed and not existing.is_status_notified(current_status) and current_status in tmp.STATUS_NOTIFY
    if should_notify:
        is_problem = current_status in {"Cancelled", "UnSupplied", "Returned", "Refunded", "UnDelivered"}
        wants = intg.notify_cancel if is_problem else intg.notify_status_change
        if wants:
            existing.mark_status_notified(current_status)
            db.session.commit()
            send_to_user(
                user,
                tmp.format_status_message(order_data, current_status),
                wa=[
                    f"{status_label(current_status)} · Trendyol Pazaryeri",
                    fields["order_number"],
                    tmp.whatsapp_items_summary(order_data),
                    f"{fields['total_price']:.2f} ₺",
                ],
            )
            return
    db.session.commit()


@webhooks_bp.route("/yemeksepeti/order", methods=["POST"])
def yemeksepeti_order():
    if not _check_yemeksepeti_token():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _ok("ignored")

    store_id = ys.store_id(payload)
    match_keys = ys.webhook_match_keys(payload)
    intg = None
    if store_id:
        intg = Integration.query.filter_by(
            platform=ys.PLATFORM, ys_store_id=store_id, is_active=True
        ).first()
    if not intg and match_keys:
        integrations = Integration.query.filter_by(
            platform=ys.PLATFORM, is_active=True
        ).all()
        intg = next(
            (
                candidate
                for candidate in integrations
                if {candidate.ys_store_id, candidate.ys_vendor_id} & match_keys
            ),
            None,
        )
    if not intg:
        print(f"[YEMEKSEPETI] eşleşen restoran yok (store={store_id})")
        return _ok("no matching store")

    user = db.session.get(User, intg.user_id)
    fields = ys.extract_order_fields(payload)
    if not fields["external_id"]:
        return _ok("missing order id")

    existing = Order.query.filter_by(
        user_id=intg.user_id, platform=ys.PLATFORM, external_id=fields["external_id"]
    ).first()
    current_status = fields["status"]

    if not existing:
        order = Order(
            user_id=intg.user_id,
            platform=ys.PLATFORM,
            raw_json=json.dumps(payload, ensure_ascii=False),
            **fields,
        )
        order.mark_status_notified("INITIAL")
        db.session.add(order)
        db.session.commit()

        if current_status == ys.STATUS_CANCELLED:
            should_notify = intg.notify_cancel
        else:
            should_notify = intg.notify_new_order
        if should_notify:
            amount = f"{fields['total_price']:.2f} ₺"
            send_to_user(
                user,
                ys.format_cancelled(payload) if current_status == ys.STATUS_CANCELLED else ys.format_order_created(payload),
                wa=[
                    "Sipariş iptal · Yemeksepeti" if current_status == ys.STATUS_CANCELLED else "Yeni sipariş · Yemeksepeti",
                    fields["order_number"],
                    ys.summarize_items(payload),
                    amount,
                ],
            )
        return _ok("created")

    status_changed = existing.status != current_status
    existing.status = current_status
    existing.order_number = fields["order_number"] or existing.order_number
    existing.total_price = fields["total_price"]
    existing.payment_type = fields["payment_type"]
    existing.customer_note = fields["customer_note"]
    existing.raw_json = json.dumps(payload, ensure_ascii=False)

    if status_changed and current_status in ys.STATUS_NOTIFY and not existing.is_status_notified(current_status):
        is_cancelled = current_status == ys.STATUS_CANCELLED
        wants = intg.notify_cancel if is_cancelled else intg.notify_status_change
        if wants:
            existing.mark_status_notified(current_status)
            db.session.commit()
            amount = f"{fields['total_price']:.2f} ₺"
            send_to_user(
                user,
                ys.format_cancelled(payload) if is_cancelled else ys.format_status(payload),
                wa=[
                    "Sipariş iptal · Yemeksepeti" if is_cancelled else f"{status_label(current_status)} · Yemeksepeti",
                    fields["order_number"],
                    ys.summarize_items(payload),
                    amount,
                ],
            )
            return _ok("status-notified")

    db.session.commit()
    return _ok("updated")


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
    already_notified = bool(
        order
        and (
            order.is_status_notified("Cancelled")
            or order.is_status_notified("Rejected")
        )
    )
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
    if intg.notify_cancel and not already_notified:
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
