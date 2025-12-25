from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from parking_system import ParkingSystem
from models import ReservationStatus


app = Flask(__name__)
app.secret_key = "dev-secret-key"

system = ParkingSystem()
system.initialize_spots()

# -------------------------
# 共通：ロールチェック
# -------------------------
def require_role(role):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if session.get("role") != role:
                flash("権限がありません", "error")
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return inner
    return wrapper

# -------------------------
# ログイン
# -------------------------
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username")
        pw = request.form.get("password")

        if user == "admin" and pw == "admin":
            session["user"] = "admin"
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        if user and pw:
            session["user"] = user
            session["role"] = "user"
            return redirect(url_for("user_dashboard"))

        flash("ログイン失敗", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------
# ユーザー画面
# -------------------------
@app.route("/user")
@require_role("user")
def user_dashboard():
    reservations = [
        r for r in system.list_reservations()
        if r.status in (
            ReservationStatus.RESERVATION,
            ReservationStatus.WAITING,
            ReservationStatus.ACTIVE,
        )
    ]

    return render_template(
        "user/dashboard.html",
        reservations=reservations,
        ReservationStatus=ReservationStatus   # ← これを追加
    )



@app.route("/user/reserve", methods=["GET", "POST"])
@require_role("user")
def user_reserve():
    if request.method == "POST":
        r = system.reserve(
            license_plate=request.form["license_plate"],
            start_time=int(request.form["start_time"]),
            end_time=int(request.form["end_time"]),
            spot_type=request.form["spot_type"]
        )
        if r:
            flash("予約成功", "success")
            return redirect(url_for("user_dashboard"))
        flash("予約失敗", "error")

    return render_template("user/reserve.html")

@app.route("/user/checkin/<reservation_id>", methods=["POST"])
@require_role("user")
def user_checkin(reservation_id):
    ok, msg = system.request_check_in(reservation_id)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("user_dashboard"))

@app.route("/user/checkout/<reservation_id>", methods=["POST"])
@require_role("user")
def user_checkout(reservation_id):
    fee = system.check_out(reservation_id)
    if fee is not None:
        flash(f"出庫完了 料金：{fee}", "success")
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

    return render_template(
        "admin/dashboard.html",
        waiting=waiting,
        active=active,
        history=history,
        queue_size=system.get_entry_queue_size(),
        ReservationStatus=ReservationStatus   # ← これを追加
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
