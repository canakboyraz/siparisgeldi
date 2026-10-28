"""Damga kartı: müşterinin QR/NFC ile açtığı sayfalar ve işletme paneli."""
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeSerializer

import loyalty
from extensions import db
from models import LoyaltyCustomer, LoyaltyProgram, LoyaltyRequest

loyalty_public_bp = Blueprint("loyalty_public", __name__)
loyalty_bp = Blueprint("loyalty", __name__)


# ── Müşteri tarafı ───────────────────────────────────────────────────────────

def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="loyalty-card")


def _active_program(token):
    program = LoyaltyProgram.query.filter_by(token=token).first()
    if not program:
        abort(404)
    return program


def _customer_from_key(program, raw):
    """İmzalı kart anahtarından (çerez ya da kişiye özel link) müşteriyi bulur."""
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
    except BadSignature:
        return None
    if not isinstance(data, dict) or data.get("p") != program.id:
        return None
    return loyalty.find_customer(program, data.get("c"))


def _cookie_customer(program):
    return _customer_from_key(program, request.cookies.get(f"{loyalty.COOKIE_PREFIX}{program.id}"))


def card_key(program, customer) -> str:
    return _serializer().dumps({"p": program.id, "c": customer.id})


def _card_url(program, customer):
    return url_for("loyalty_public.my_card", token=program.token, key=card_key(program, customer))


def _with_cookie(response, program, customer):
    response.set_cookie(f"{loyalty.COOKIE_PREFIX}{program.id}", card_key(program, customer),
                        max_age=loyalty.COOKIE_MAX_AGE, httponly=True, samesite="Lax",
                        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
    return response


@loyalty_public_bp.route("/k/<token>", methods=["GET", "POST"])
def join(token):
    """QR/NFC'nin açtığı adres. Tanınan müşteri için damga isteği oluşturur, yeni müşteriye kayıt formu gösterir."""
    program = _active_program(token)
    if not program.is_active:
        return render_template("loyalty/closed.html", program=program)
    customer = _cookie_customer(program)
    if request.method == "GET":
        if customer:
            loyalty.request_stamp(program, customer, "visit")
            return _with_cookie(redirect(_card_url(program, customer)), program, customer)
        return render_template("loyalty/join.html", program=program, form={})

    name = " ".join((request.form.get("name") or "").split())[:40]
    phone = loyalty.normalize_phone(request.form.get("phone"))
    existing = LoyaltyCustomer.query.filter_by(program_id=program.id, phone=phone).first() if phone else None
    error = None
    if not phone:
        error = "Telefon numaranı 05XX XXX XX XX şeklinde yaz."
    elif existing:
        pass  # Kayıtlı numara: ad ve onay ilk kayıtta alındı, sadece telefon yeterli.
    elif len(name) < 2:
        error = "Bu numarayla kart yok. Yeni kart için adını da yaz."
    elif request.form.get("consent") != "1":
        error = "Devam etmek için aydınlatma metnini onayla."
    if error:
        return render_template("loyalty/join.html", program=program, error=error,
                               form={"name": name, "phone": request.form.get("phone", "")}), 400
    if existing:
        # Daha önce katılmış (ör. yeni telefon): hoş geldin damgası verilmez, normal ziyaret isteği oluşur.
        customer = existing
        loyalty.request_stamp(program, customer, "visit")
    else:
        customer = LoyaltyCustomer(program_id=program.id, name=name, phone=phone)
        db.session.add(customer)
        db.session.commit()
        loyalty.request_stamp(program, customer, "welcome")
    return _with_cookie(redirect(_card_url(program, customer)), program, customer)


def _render_card(program, customer):
    key = card_key(program, customer)
    return render_template("loyalty/card.html", program=program, customer=customer, card_key=key,
                           card_url=url_for("loyalty_public.my_card", token=program.token, key=key, _external=True),
                           state=loyalty.card_state(program, customer))


@loyalty_public_bp.route("/k/<token>/kart")
def card(token):
    program = _active_program(token)
    customer = _cookie_customer(program)
    if not customer:
        return redirect(url_for("loyalty_public.join", token=token))
    return _render_card(program, customer)


@loyalty_public_bp.route("/k/<token>/kartim/<key>")
def my_card(token, key):
    """Kişiye özel kart linki: sadece kartı gösterir, damga isteği oluşturmaz (ana ekrana eklenen adres)."""
    program = _active_program(token)
    customer = _customer_from_key(program, key)
    if not customer:
        return redirect(url_for("loyalty_public.join", token=token))
    return _with_cookie(make_response(_render_card(program, customer)), program, customer)


@loyalty_public_bp.route("/k/<token>/kartim/<key>/manifest.webmanifest")
def card_manifest(token, key):
    program = _active_program(token)
    customer = _customer_from_key(program, key)
    if not customer:
        abort(404)
    start = url_for("loyalty_public.my_card", token=token, key=key)
    response = jsonify({"name": f"{program.name} damga kartım", "short_name": program.name[:12],
                        "start_url": start, "scope": start, "display": "standalone",
                        "background_color": "#FBF7F2", "theme_color": "#D4411F"})
    response.mimetype = "application/manifest+json"
    return response


@loyalty_public_bp.route("/k/<token>/durum")
def status(token):
    program = _active_program(token)
    customer = _customer_from_key(program, request.args.get("a")) or _cookie_customer(program)
    if not customer:
        return jsonify({"error": "unknown"}), 404
    response = jsonify(loyalty.card_state(program, customer))
    response.headers["Cache-Control"] = "no-store"
    return response


@loyalty_public_bp.post("/k/<token>/cikis")
def forget(token):
    program = _active_program(token)
    response = make_response(redirect(url_for("loyalty_public.join", token=token)))
    response.delete_cookie(f"{loyalty.COOKIE_PREFIX}{program.id}")
    return response


# ── İşletme paneli ───────────────────────────────────────────────────────────

def _int(name, default, low, high):
    try:
        return max(low, min(high, int(request.form.get(name, default))))
    except (TypeError, ValueError):
        return default


@loyalty_bp.route("", methods=["GET", "POST"])
@login_required
def setup():
    program = loyalty.get_program(current_user)
    if request.method == "POST":
        if not program:
            program = LoyaltyProgram(user_id=current_user.id, token=loyalty.new_token(), name=current_user.name[:80])
            db.session.add(program)
        program.name = " ".join((request.form.get("name") or program.name).split())[:80] or current_user.name[:80]
        program.reward = " ".join((request.form.get("reward") or program.reward or "").split())[:80] or "1 kahve bedava"
        program.stamps_required = _int("stamps_required", 6, 2, 30)
        program.welcome_stamps = _int("welcome_stamps", 2, 1, 10)
        program.stamps_per_visit = _int("stamps_per_visit", 1, 1, 5)
        program.cooldown_minutes = _int("cooldown_minutes", 30, 0, 24 * 60)
        program.is_active = request.form.get("is_active", "1") == "1"
        db.session.commit()
        flash("Damga kartı ayarları kaydedildi.", "success")
        return redirect(url_for("loyalty.setup"))

    customers, pending, stats = [], [], {}
    q = (request.args.get("q") or "").strip()
    if program:
        query = LoyaltyCustomer.query.filter_by(program_id=program.id)
        if q:
            digits = "".join(ch for ch in q if ch.isdigit())
            like = f"%{q}%"
            query = query.filter(db.or_(LoyaltyCustomer.name.ilike(like),
                                        LoyaltyCustomer.phone.like(f"%{digits}%") if digits else db.false()))
        customers = query.order_by(LoyaltyCustomer.last_visit_at.desc().nullslast(), LoyaltyCustomer.id.desc()).limit(100).all()
        pending = (LoyaltyRequest.query.filter_by(program_id=program.id, status="pending")
                   .order_by(LoyaltyRequest.id.asc()).all())
        base = LoyaltyCustomer.query.filter_by(program_id=program.id)
        stats = {
            "customers": base.count(),
            "stamps": db.session.query(db.func.coalesce(db.func.sum(LoyaltyCustomer.lifetime_stamps), 0))
                      .filter(LoyaltyCustomer.program_id == program.id).scalar(),
            "rewards": db.session.query(db.func.coalesce(db.func.sum(LoyaltyCustomer.rewards_redeemed), 0))
                       .filter(LoyaltyCustomer.program_id == program.id).scalar(),
            "ready": base.filter(LoyaltyCustomer.stamps >= program.stamps_required).count(),
        }
    return render_template("loyalty/setup.html", program=program, customers=customers, pending=pending,
                           stats=stats, q=q, mask_phone=loyalty.mask_phone,
                           join_url=url_for("loyalty_public.join", token=program.token, _external=True) if program else "")


def _request_json(req, program):
    customer = req.customer
    return {
        "id": req.id, "code": req.code, "kind": req.kind, "stamps": req.stamps,
        "name": customer.name, "phone": loyalty.mask_phone(customer.phone),
        "current": customer.stamps, "required": program.stamps_required,
        "reward_ready": customer.stamps >= program.stamps_required, "reward": program.reward,
        "customer_id": customer.id,
        "age_seconds": int((datetime.utcnow() - req.created_at).total_seconds()) if req.created_at else 0,
    }


@loyalty_bp.route("/bekleyen")
@login_required
def pending_json():
    program = loyalty.get_program(current_user)
    if not program:
        return jsonify({"items": []})
    items = (LoyaltyRequest.query.filter_by(program_id=program.id, status="pending")
             .order_by(LoyaltyRequest.id.asc()).limit(10).all())
    response = jsonify({"items": [_request_json(r, program) for r in items]})
    response.headers["Cache-Control"] = "no-store"
    return response


def _next_url():
    target = request.form.get("next") or ""
    return target if target.startswith("/") and not target.startswith("//") else url_for("loyalty.setup")


def _wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


@loyalty_bp.post("/istek/<int:req_id>/<action>")
@login_required
def decide(req_id, action):
    program = loyalty.get_program(current_user)
    req = LoyaltyRequest.query.filter_by(id=req_id, program_id=program.id).first_or_404() if program else abort(404)
    ok = loyalty.approve(req) if action == "onay" else loyalty.reject(req) if action == "red" else abort(404)
    if _wants_json():
        return jsonify({"ok": ok, "status": req.status, "current": req.customer.stamps,
                        "reward_ready": req.customer.stamps >= program.stamps_required})
    if ok:
        flash(f"{req.customer.name}: +{req.stamps} damga eklendi." if action == "onay" else "İstek reddedildi.", "success")
    else:
        flash("Bu istek zaten sonuçlanmış.", "warning")
    return redirect(_next_url())


@loyalty_bp.post("/musteri/<int:customer_id>/odul")
@login_required
def give_reward(customer_id):
    program = loyalty.get_program(current_user) or abort(404)
    customer = loyalty.find_customer(program, customer_id) or abort(404)
    ok = loyalty.redeem(program, customer)
    if _wants_json():
        return jsonify({"ok": ok, "current": customer.stamps})
    flash(f"{customer.name}: {program.reward} verildi." if ok else "Ödül için yeterli damga yok.", "success" if ok else "warning")
    return redirect(_next_url())


@loyalty_bp.post("/musteri/<int:customer_id>/sil")
@login_required
def delete_customer(customer_id):
    program = loyalty.get_program(current_user) or abort(404)
    customer = loyalty.find_customer(program, customer_id) or abort(404)
    db.session.delete(customer)
    db.session.commit()
    flash("Müşteri ve damga geçmişi silindi.", "success")
    return redirect(url_for("loyalty.setup"))


HISTORY_FILTERS = {
    "": ("Tümü", None),
    "bekleyen": ("Bekleyen", ("pending", None)),
    "onay": ("Onaylanan", ("approved", ("welcome", "visit"))),
    "red": ("Reddedilen", ("rejected", None)),
    "odul": ("Ödül", ("approved", ("reward",))),
}


@loyalty_bp.route("/hareketler")
@login_required
def history():
    """Tüm damga istekleri ve ödüller: bekleyen, onaylanan, reddedilen; tarih ve müşteri filtresi."""
    import pytz
    from datetime import date as _date, timedelta
    program = loyalty.get_program(current_user) or abort(404)
    tz = pytz.timezone("Europe/Istanbul")
    status_key = request.args.get("durum", "")
    status_key = status_key if status_key in HISTORY_FILTERS else ""
    q = (request.args.get("q") or "").strip()
    try:
        day_from = _date.fromisoformat(request.args.get("baslangic", ""))
    except ValueError:
        day_from = None
    try:
        day_to = _date.fromisoformat(request.args.get("bitis", ""))
    except ValueError:
        day_to = None

    def to_utc(day):
        return tz.localize(datetime.combine(day, datetime.min.time())).astimezone(pytz.utc).replace(tzinfo=None)

    base = (LoyaltyRequest.query.join(LoyaltyCustomer, LoyaltyRequest.customer_id == LoyaltyCustomer.id)
            .filter(LoyaltyRequest.program_id == program.id))
    if day_from:
        base = base.filter(LoyaltyRequest.created_at >= to_utc(day_from))
    if day_to:
        base = base.filter(LoyaltyRequest.created_at < to_utc(day_to + timedelta(days=1)))
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        base = base.filter(db.or_(LoyaltyCustomer.name.ilike(f"%{q}%"),
                                  LoyaltyCustomer.phone.like(f"%{digits}%") if digits else db.false()))

    def apply(query, key):
        rule = HISTORY_FILTERS[key][1]
        if not rule:
            return query
        status, kinds = rule
        query = query.filter(LoyaltyRequest.status == status)
        return query.filter(LoyaltyRequest.kind.in_(kinds)) if kinds else query

    counts = {key: apply(base, key).count() for key in HISTORY_FILTERS}
    page = request.args.get("page", 1, type=int)
    rows = apply(base, status_key).order_by(LoyaltyRequest.id.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template("loyalty/history.html", program=program, rows=rows, counts=counts,
                           filters=HISTORY_FILTERS, status_key=status_key, q=q,
                           day_from=day_from.isoformat() if day_from else "",
                           day_to=day_to.isoformat() if day_to else "", mask_phone=loyalty.mask_phone)


@loyalty_bp.route("/afis")
@login_required
def poster():
    program = loyalty.get_program(current_user) or abort(404)
    return render_template("loyalty/poster.html", program=program,
                           join_url=url_for("loyalty_public.join", token=program.token, _external=True))
