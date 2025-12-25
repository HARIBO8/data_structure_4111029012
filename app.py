from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Optional

from parking_system import ParkingSystem
from models import ReservationStatus

app = Flask(__name__)
app.secret_key = "dev-secret-key"

system = ParkingSystem()
system.initialize_spots()

# -------------------------
# ユーザーDB（簡易：メモリ）
# ※ サーバー再起動で消える
# -------------------------
from werkzeug.security import generate_password_hash

USERS = {
    "A": generate_password_hash("a"),
    "B": generate_password_hash("b"),
    "C": generate_password_hash("c"),
}

# -------------------------
# 共通：ロールチェック
# -------------------------
def require_role(role):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if session.get("role") != role:
                flash("您沒有操作權限", "error")
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return inner
    return wrapper


def current_username() -> Optional[str]:
    u = session.get("user")
    return u if isinstance(u, str) else None


def get_reservation_or_none(reservation_id: str):
    return system.reservations.get(reservation_id)


def ensure_owner(reservation_id: str) -> bool:
    u = current_username()
    r = get_reservation_or_none(reservation_id)
    if u is None or r is None:
        return False
    return getattr(r, "username", None) == u


# -------------------------
# ルート
# -------------------------
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("login"))


# -------------------------
# ユーザー登録
# -------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if session.get("role") == "user":
        return redirect(url_for("user_dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        pw1 = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""

        if not username:
            flash("請輸入使用者名稱", "error")
            return render_template("register.html")

        if username == "admin":
            flash("admin 無法註冊為一般使用者", "error")
            return render_template("register.html")

        if username in USERS:
            flash("此使用者名稱已被使用", "error")
            return render_template("register.html")

        if not pw1:
            flash("請輸入密碼", "error")
            return render_template("register.html")

        if pw1 != pw2:
            flash("兩次輸入的密碼不一致", "error")
            return render_template("register.html")

        USERS[username] = generate_password_hash(pw1)
        flash("註冊成功，請登入系統", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# -------------------------
# ログイン
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if session.get("role") == "user":
        return redirect(url_for("user_dashboard"))

    if request.method == "POST":
        user = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""

        if user == "admin" and pw == "admin":
            session["user"] = "admin"
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        if user in USERS and check_password_hash(USERS[user], pw):
            session["user"] = user
            session["role"] = "user"
            return redirect(url_for("user_dashboard"))

        flash("登入失敗：使用者名稱或密碼錯誤", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# ユーザー画面（ユーザー別）
# -------------------------
@app.route("/user")
@require_role("user")
def user_dashboard():
    u = current_username()

    reservations = [
        r for r in system.list_reservations()
        if getattr(r, "username", None) == u
        and r.status in (
            ReservationStatus.RESERVATION,
            ReservationStatus.WAITING,
            ReservationStatus.ACTIVE,
        )
    ]
    return render_template(
        "user/dashboard.html",
        reservations=reservations,
        ReservationStatus=ReservationStatus,
    )


@app.route("/user/reserve", methods=["GET", "POST"])
@require_role("user")
def user_reserve():
    if request.method == "POST":
        u = current_username()
        r = system.reserve(
            username=u,
            license_plate=request.form["license_plate"],
            start_time=int(request.form["start_time"]),
            end_time=int(request.form["end_time"]),
            spot_type=request.form["spot_type"],
        )
        if r:
            flash("預約成功", "success")
            return redirect(url_for("user_dashboard"))
        flash("預約失敗", "error")

    return render_template("user/reserve.html")


@app.route("/user/checkin/<reservation_id>", methods=["POST"])
@require_role("user")
def user_checkin(reservation_id):
    if not ensure_owner(reservation_id):
        flash("無法操作其他使用者的預約", "error")
        return redirect(url_for("user_dashboard"))

    ok, msg = system.request_check_in(reservation_id)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("user_dashboard"))


@app.route("/user/checkout/<reservation_id>", methods=["POST"])
@require_role("user")
def user_checkout(reservation_id):
    if not ensure_owner(reservation_id):
        flash("無法操作其他使用者的預約", "error")
        return redirect(url_for("user_dashboard"))

    fee = system.check_out(reservation_id)
    if fee is not None:
        flash(f"出庫完成，費用：{fee}", "success")
    else:
        flash("出庫失敗", "error")
    return redirect(url_for("user_dashboard"))


# -------------------------
# 管理者画面
# -------------------------
@app.route("/admin")
@require_role("admin")
def admin_dashboard():
    waiting = system.list_reservations(ReservationStatus.WAITING)
    active = system.list_reservations(ReservationStatus.ACTIVE)
    history = system.list_history()

    spot_overview = system.get_spot_overview()

    return render_template(
        "admin/dashboard.html",
        waiting=waiting,
        active=active,
        history=history,
        queue_size=system.get_entry_queue_size(),
        spot_overview=spot_overview,
        ReservationStatus=ReservationStatus,
    )


@app.route("/admin/process_checkin", methods=["POST"])
@require_role("admin")
def admin_process_checkin():
    ok, msg = system.process_next_check_in()
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/undo", methods=["POST"])
@require_role("admin")
def admin_undo():
    ok, msg = system.undo_last()
    flash(msg, "success" if ok else "error")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
