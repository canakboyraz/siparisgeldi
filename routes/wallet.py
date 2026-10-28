"""Apple PassKit web servisi: iPhone'lar Cüzdan'daki damga kartını buradan kaydeder ve günceller.

Apple'ın beklediği uç noktalar (webServiceURL = https://<alan>/wallet):
  POST   /wallet/v1/devices/<cihaz>/registrations/<passType>/<seri>   kartı kaydet
  DELETE /wallet/v1/devices/<cihaz>/registrations/<passType>/<seri>   kaydı sil
  GET    /wallet/v1/devices/<cihaz>/registrations/<passType>           değişen kartlar
  GET    /wallet/v1/passes/<passType>/<seri>                           güncel .pkpass
  POST   /wallet/v1/log                                                hata günlüğü
"""
import logging
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime

from flask import Blueprint, Response, jsonify, request, url_for

import wallet
from extensions import db
from models import LoyaltyCustomer, LoyaltyProgram, WalletRegistration

wallet_bp = Blueprint("wallet", __name__, url_prefix="/wallet/v1")
log = logging.getLogger("wallet")


def _customer_for(serial):
    ids = wallet.parse_serial(serial)
    if not ids:
        return None, None
    program = db.session.get(LoyaltyProgram, ids[0])
    customer = LoyaltyCustomer.query.filter_by(id=ids[1], program_id=ids[0]).first() if program else None
    return program, customer


def _authorized(pass_type, serial):
    return (wallet.is_configured() and pass_type == wallet._cfg("APPLE_PASS_TYPE_ID")
            and wallet.check_auth(serial, request.headers.get("Authorization")))


def web_service_url():
    return request.host_url.rstrip("/") + "/wallet"


def card_url(program, customer):
    from routes.loyalty import card_key
    return url_for("loyalty_public.my_card", token=program.token, key=card_key(program, customer), _external=True)


def pkpass_response(program, customer):
    body = wallet.build_pkpass(program, customer, card_url(program, customer), web_service_url())
    response = Response(body, mimetype="application/vnd.apple.pkpass")
    response.headers["Content-Disposition"] = 'inline; filename="damga-karti.pkpass"'
    response.headers["Last-Modified"] = format_datetime(wallet.updated_at(customer).replace(tzinfo=timezone.utc), usegmt=True)
    response.headers["Cache-Control"] = "no-store"
    return response


@wallet_bp.route("/devices/<device_id>/registrations/<pass_type>/<serial>", methods=["POST", "DELETE"])
def register(device_id, pass_type, serial):
    if not _authorized(pass_type, serial):
        return "", 401
    program, customer = _customer_for(serial)
    if not customer:
        return "", 401
    existing = WalletRegistration.query.filter_by(device_id=device_id[:128], serial=serial).first()
    if request.method == "DELETE":
        if existing:
            db.session.delete(existing)
            db.session.commit()
        return "", 200
    push_token = ((request.get_json(silent=True) or {}).get("pushToken") or "").strip()[:200]
    if not push_token:
        return "", 400
    if existing:
        existing.push_token = push_token
        db.session.commit()
        return "", 200
    db.session.add(WalletRegistration(device_id=device_id[:128], push_token=push_token,
                                      serial=serial, customer_id=customer.id))
    db.session.commit()
    return "", 201


@wallet_bp.get("/devices/<device_id>/registrations/<pass_type>")
def updated_serials(device_id, pass_type):
    if not wallet.is_configured() or pass_type != wallet._cfg("APPLE_PASS_TYPE_ID"):
        return "", 404
    try:
        since = int(request.args.get("passesUpdatedSince") or 0)
    except ValueError:
        since = 0
    serials, latest = [], since
    for reg in WalletRegistration.query.filter_by(device_id=device_id[:128]).all():
        _, customer = _customer_for(reg.serial)
        if not customer:
            continue
        stamp = int(wallet.updated_at(customer).replace(tzinfo=timezone.utc).timestamp())
        if stamp > since:
            serials.append(reg.serial)
            latest = max(latest, stamp)
    if not serials:
        return "", 204
    return jsonify({"serialNumbers": serials, "lastUpdated": str(latest)})


@wallet_bp.get("/passes/<pass_type>/<serial>")
def latest_pass(pass_type, serial):
    if not _authorized(pass_type, serial):
        return "", 401
    program, customer = _customer_for(serial)
    if not customer:
        return "", 404
    since = request.headers.get("If-Modified-Since")
    if since:
        try:
            changed = wallet.updated_at(customer).replace(tzinfo=timezone.utc, microsecond=0)
            if changed <= parsedate_to_datetime(since):
                return "", 304
        except (TypeError, ValueError):
            pass
    return pkpass_response(program, customer)


@wallet_bp.post("/log")
def device_log():
    for line in ((request.get_json(silent=True) or {}).get("logs") or [])[:20]:
        log.warning("[WALLET] cihaz: %s", str(line)[:300])
    return "", 200
