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
    import wallet
    return render_template("loyalty/card.html", program=program, customer=customer, card_key=key,
                           wallet_ready=wallet.is_configured(),
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
    icons = [{"src": url_for("loyalty_public.app_icon", size=px), "sizes": f"{px}x{px}", "type": "image/png",
              "purpose": "any maskable"} for px in (192, 512)]
    response = jsonify({"name": f"{program.name} damga kartım", "short_name": program.name[:12],
                        "id": start, "start_url": start, "scope": "/k/", "display": "standalone",
                        "background_color": "#153028", "theme_color": "#153028", "icons": icons})
    response.mimetype = "application/manifest+json"
    return response


@loyalty_public_bp.route("/k/ikon-<int:size>.png")
def app_icon(size):
    """Ana ekran / uygulama simgesi (damga işareti)."""
    import wallet
    if size not in (180, 192, 512):
        abort(404)
    response = make_response(wallet.app_icon_png(size))
    response.mimetype = "image/png"
    response.headers["Cache-Control"] = "public, max-age=604800"
    return response


SERVICE_WORKER_JS = """// SiparişGeldi damga kartı: ana ekrana eklenebilir uygulama + çevrimdışı son görünüm
const CACHE = "sg-kart-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || req.mode !== "navigate") return;
  e.respondWith(fetch(req).then((res) => {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
    return res;
  }).catch(() => caches.match(req)));
});
"""


@loyalty_public_bp.route("/k/sw.js")
def service_worker():
    response = make_response(SERVICE_WORKER_JS)
    response.mimetype = "application/javascript"
    response.headers["Cache-Control"] = "no-cache"
    return response


@loyalty_public_bp.route("/k/<token>/kartim/<key>/cuzdan.pkpass")
def wallet_pass(token, key):
    """Apple Cüzdan'a ekle: müşteriye özel imzalı .pkpass."""
    import wallet
    from routes.wallet import pkpass_response
    program = _active_program(token)
    customer = _customer_from_key(program, key)
    if not customer or not wallet.is_configured():
        abort(404)
    try:
        return pkpass_response(program, customer)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("[WALLET] .pkpass üretilemedi")
        return render_template("loyalty/closed.html", program=program,
                               message="Cüzdan kartı şu an hazırlanamadı. Kartın bu sayfada geçerli."), 503


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
    import wallet
    import loyalty_notify
    wallet_info = {}
    if program:
        holders = loyalty_notify.wallet_customers(program)
        wallet_info = {
            "ready": wallet.is_configured(),
            "holders": holders.count(),
            "due": len(loyalty_notify.due_reminders(program)),
            "last": holders.filter(LoyaltyCustomer.wallet_message_at.isnot(None))
                    .order_by(LoyaltyCustomer.wallet_message_at.desc()).first(),
        }
    return render_template("loyalty/setup.html", program=program, customers=customers, pending=pending,
                           stats=stats, q=q, mask_phone=loyalty.mask_phone, wallet_info=wallet_info,
                           join_url=url_for("loyalty_public.join", token=program.token, _external=True) if program else "")


@loyalty_bp.post("/bildirim")
@login_required
def notify_settings():
    program = loyalty.get_program(current_user) or abort(404)
    program.notify_enabled = request.form.get("notify_enabled") == "1"
    program.notify_inactive_days = _int("notify_inactive_days", 7, 1, 90)
    program.notify_min_hours = 24 if request.form.get("notify_min_hours") not in ("72", "168") else int(request.form["notify_min_hours"])
    program.notify_max_reminders = _int("notify_max_reminders", 3, 1, 30)
    db.session.commit()
    flash("Bildirim ayarları kaydedildi.", "success")
    return redirect(url_for("loyalty.setup") + "#bildirimler")


@loyalty_bp.post("/duyuru")
@login_required
def announce():
    import loyalty_notify
    program = loyalty.get_program(current_user) or abort(404)
    text = " ".join((request.form.get("message") or "").split())[:140]
    if len(text) < 5:
        flash("Duyuru metni en az 5 karakter olmalı.", "error")
        return redirect(url_for("loyalty.setup") + "#bildirimler")
    sent, skipped = loyalty_notify.broadcast(program, text)
    if sent:
        msg = f"Duyuru {sent} kişinin Cüzdan kartına gönderildi."
        if skipped:
            msg += f" {skipped} kişi son bildirimini yakın zamanda aldığı için atlandı."
        flash(msg, "success")
    else:
        flash("Duyuru gönderilmedi: Cüzdan'da kartı olan ya da sıklık sınırına uyan müşteri yok.", "error")
    return redirect(url_for("loyalty.setup") + "#bildirimler")


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
    from models import WalletRegistration
    WalletRegistration.query.filter_by(customer_id=customer.id).delete()
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


# ── Kasada kart okutma ───────────────────────────────────────────────────────

def _key_from_code(program, code):
    """Okutulan QR: kişiye özel kart linki (…/k/<token>/kartim/<anahtar>) ya da yalnız anahtar."""
    code = (code or "").strip()
    if "/kartim/" in code:
        head, _, key = code.partition("/kartim/")
        if not head.rstrip("/").endswith(f"/k/{program.token}"):
            return None
        return key.split("/")[0].split("?")[0]
    return code if "." in code and len(code) < 200 else None


def _scan_json(program, customer, status, req=None, left=0):
    return {
        "ok": status == "ok", "status": status, "customer_id": customer.id, "name": customer.name,
        "phone": loyalty.mask_phone(customer.phone), "added": req.stamps if req else 0,
        "current": customer.stamps, "required": program.stamps_required,
        "reward_ready": customer.stamps >= program.stamps_required, "reward": program.reward,
        "cooldown": left,
    }


@loyalty_bp.route("/okut", methods=["GET", "POST"])
@login_required
def scan():
    """Kasada müşterinin kart QR'ını (Cüzdan / ana ekran) okut ya da telefonla bul; damga anında işlenir."""
    program = loyalty.get_program(current_user)
    if request.method == "GET":
        if not program:
            return redirect(url_for("loyalty.setup"))
        return render_template("loyalty/scan.html", program=program)
    if not program:
        abort(404)
    data = request.get_json(silent=True) or request.form
    force = str(data.get("force") or "") in ("1", "true", "True")
    customer = None
    if data.get("code"):
        customer = _customer_from_key(program, _key_from_code(program, data.get("code")))
        if not customer:
            return jsonify({"ok": False, "status": "unknown",
                            "message": "Bu kod bu işletmenin damga kartı değil."}), 404
    elif data.get("phone"):
        phone = loyalty.normalize_phone(data.get("phone"))
        customer = LoyaltyCustomer.query.filter_by(program_id=program.id, phone=phone).first() if phone else None
        if not customer:
            return jsonify({"ok": False, "status": "unknown",
                            "message": "Bu numarayla kart yok. Müşteri kasadaki QR'ı okutup kayıt olabilir."}), 404
    else:
        abort(400)
    status, req, left = loyalty.stamp_now(program, customer, force=force)
    return jsonify(_scan_json(program, customer, status, req, left))
