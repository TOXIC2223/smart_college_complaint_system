import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "complaints.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','staff','admin')),
        department TEXT DEFAULT '',
        semester TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id TEXT UNIQUE NOT NULL,
        student_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        location TEXT NOT NULL,
        description TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Submitted',
        assigned_staff_id INTEGER,
        image_filename TEXT,
        resolution_note TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(assigned_staff_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER UNIQUE NOT NULL,
        rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
        comment TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    seed_users(db)
    db.commit()
    db.close()


def seed_users(db):
    users = [
        ("Admin User", "admin@college.com", "admin123", "admin", "Administration", ""),
        ("Staff Member", "staff@college.com", "staff123", "staff", "Computer", ""),
        ("Student User", "student@college.com", "student123", "student", "Computer", "4")
    ]
    for name, email, password, role, department, semester in users:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO users
                   (name,email,password,role,department,semester,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (name, email, generate_password_hash(password), role,
                 department, semester, now())
            )


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    db.close()
    return user


@app.context_processor
def inject_globals():
    return {"current_user": current_user()}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login"))
            if user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def notify(db, user_id, message):
    db.execute(
        "INSERT INTO notifications (user_id,message,created_at) VALUES (?,?,?)",
        (user_id, message, now())
    )


def suggest_priority(category, description):
    text = f"{category} {description}".lower()
    high_words = [
        "fire", "shock", "electric", "electrical", "danger", "leak",
        "server down", "internet down", "security", "emergency"
    ]
    medium_words = [
        "computer", "projector", "printer", "fan", "light",
        "water", "broken", "network"
    ]
    if any(word in text for word in high_words):
        return "High"
    if any(word in text for word in medium_words):
        return "Medium"
    return "Low"


@app.route("/")
def index():
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()["n"]
    resolved = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE status='Resolved'").fetchone()["n"]
    pending = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE status='Submitted' OR status='Assigned' OR status='In Progress'").fetchone()["n"]
    avg_rating = db.execute("SELECT AVG(rating) AS avg FROM feedback").fetchone()["avg"]
    db.close()

    rating_display = f"{avg_rating:.1f}★" if avg_rating else "—"

    return render_template("index.html",
                          total=total,
                          resolved=resolved,
                          pending=pending,
                          rating=rating_display)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        db.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            flash("Welcome back!", "success")
            if user["role"] == "student":
                return redirect(url_for("student_dashboard"))
            if user["role"] == "staff":
                return redirect(url_for("staff_dashboard"))
            return redirect(url_for("admin_dashboard"))

        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        semester = request.form.get("semester", "").strip()

        if not all([name, email, password]):
            flash("Name, email and password are required.", "danger")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                """INSERT INTO users
                   (name,email,password,role,department,semester,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (name, email, generate_password_hash(password), "student",
                 department, semester, now())
            )
            db.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "danger")
        finally:
            db.close()

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/student")
@login_required
@role_required("student")
def student_dashboard():
    db = get_db()
    complaints = db.execute(
        """SELECT c.*, s.name AS staff_name
           FROM complaints c
           LEFT JOIN users s ON c.assigned_staff_id = s.id
           WHERE c.student_id = ?
           ORDER BY c.created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    unread = db.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
        (session["user_id"],)
    ).fetchone()["n"]
    db.close()
    return render_template("student_dashboard.html", complaints=complaints, unread=unread)


@app.route("/complaint/new", methods=["GET", "POST"])
@login_required
@role_required("student")
def new_complaint():
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Auto")
        file = request.files.get("image")

        if not category or not location or not description:
            flash("Please fill all required fields.", "danger")
            return render_template("new_complaint.html")

        if priority == "Auto":
            priority = suggest_priority(category, description)

        filename = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only PNG, JPG, JPEG and WEBP images are allowed.", "danger")
                return render_template("new_complaint.html")
            ext = file.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        complaint_code = "CMP-" + uuid.uuid4().hex[:8].upper()
        db = get_db()
        created = now()
        db.execute(
            """INSERT INTO complaints
               (complaint_id,student_id,category,location,description,priority,
                status,image_filename,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (complaint_code, session["user_id"], category, location, description,
             priority, "Submitted", filename, created, created)
        )
        complaint_pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        admins = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
        for admin_user in admins:
            notify(db, admin_user["id"], f"New complaint {complaint_code} submitted.")
        db.commit()
        db.close()

        flash(f"Complaint submitted successfully. ID: {complaint_code}", "success")
        return redirect(url_for("complaint_detail", complaint_pk=complaint_pk))

    return render_template("new_complaint.html")


@app.route("/complaint/<int:complaint_pk>")
@login_required
def complaint_detail(complaint_pk):
    db = get_db()
    complaint = db.execute(
        """SELECT c.*, s.name AS student_name, s.email AS student_email,
                  st.name AS staff_name
           FROM complaints c
           JOIN users s ON c.student_id=s.id
           LEFT JOIN users st ON c.assigned_staff_id=st.id
           WHERE c.id=?""",
        (complaint_pk,)
    ).fetchone()

    if not complaint:
        db.close()
        abort(404)

    user = current_user()
    allowed = (
        user["role"] == "admin"
        or complaint["student_id"] == user["id"]
        or complaint["assigned_staff_id"] == user["id"]
    )
    if not allowed:
        db.close()
        abort(403)

    feedback = db.execute(
        "SELECT * FROM feedback WHERE complaint_id=?", (complaint_pk,)
    ).fetchone()
    db.close()
    return render_template("complaint_detail.html", complaint=complaint, feedback=feedback)


@app.route("/complaint/<int:complaint_pk>/feedback", methods=["POST"])
@login_required
@role_required("student")
def feedback(complaint_pk):
    rating = int(request.form.get("rating", 0))
    comment = request.form.get("comment", "").strip()
    db = get_db()
    complaint = db.execute(
        "SELECT * FROM complaints WHERE id=? AND student_id=?",
        (complaint_pk, session["user_id"])
    ).fetchone()

    if not complaint or complaint["status"] != "Resolved":
        db.close()
        abort(403)

    if not 1 <= rating <= 5:
        db.close()
        flash("Please select a rating from 1 to 5.", "danger")
        return redirect(url_for("complaint_detail", complaint_pk=complaint_pk))

    try:
        db.execute(
            "INSERT INTO feedback (complaint_id,rating,comment,created_at) VALUES (?,?,?,?)",
            (complaint_pk, rating, comment, now())
        )
        db.commit()
        flash("Thank you for your feedback.", "success")
    except sqlite3.IntegrityError:
        flash("Feedback has already been submitted.", "warning")
    finally:
        db.close()
    return redirect(url_for("complaint_detail", complaint_pk=complaint_pk))


@app.route("/staff")
@login_required
@role_required("staff")
def staff_dashboard():
    db = get_db()
    complaints = db.execute(
        """SELECT c.*, u.name AS student_name
           FROM complaints c
           JOIN users u ON c.student_id=u.id
           WHERE c.assigned_staff_id=?
           ORDER BY CASE c.priority
                    WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                    c.created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return render_template("staff_dashboard.html", complaints=complaints)


@app.route("/staff/complaint/<int:complaint_pk>", methods=["POST"])
@login_required
@role_required("staff")
def staff_update_complaint(complaint_pk):
    status = request.form.get("status", "In Progress")
    note = request.form.get("resolution_note", "").strip()
    allowed_statuses = {"Assigned", "In Progress", "Resolved"}

    if status not in allowed_statuses:
        flash("Invalid status.", "danger")
        return redirect(url_for("staff_dashboard"))

    db = get_db()
    complaint = db.execute(
        "SELECT * FROM complaints WHERE id=? AND assigned_staff_id=?",
        (complaint_pk, session["user_id"])
    ).fetchone()

    if not complaint:
        db.close()
        abort(403)

    resolved_at = now() if status == "Resolved" else None
    db.execute(
        """UPDATE complaints
           SET status=?, resolution_note=?, updated_at=?, resolved_at=?
           WHERE id=?""",
        (status, note, now(), resolved_at, complaint_pk)
    )
    notify(db, complaint["student_id"],
           f"Complaint {complaint['complaint_id']} status changed to {status}.")
    db.commit()
    db.close()

    flash("Complaint updated.", "success")
    return redirect(url_for("staff_dashboard"))


# FIX: this function was previously named `admin()`, but every redirect/url_for
# call elsewhere in the app (login(), assign_complaint(), change_priority())
# referenced the endpoint "admin_dashboard". Since Flask endpoints default to
# the function name, url_for("admin_dashboard") was raising a BuildError as
# soon as an admin logged in. Renaming the function to match fixes it.
@app.route("/admin")
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Please log in as admin first.")
        return redirect("/login")

    db = get_db()

    # Get statistics
    total_complaints = db.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()["n"]
    resolved_count = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE status='Resolved'").fetchone()["n"]
    in_progress_count = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE status='In Progress'").fetchone()["n"]
    high_priority_count = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE priority='High'").fetchone()["n"]
    submitted_count = db.execute("SELECT COUNT(*) AS n FROM complaints WHERE status='Submitted'").fetchone()["n"]

    avg_rating_result = db.execute("SELECT AVG(rating) AS avg FROM feedback").fetchone()
    avg_rating = f"{avg_rating_result['avg']:.1f}★" if avg_rating_result['avg'] else "—"

    # Get all complaints
    complaints = db.execute("SELECT * FROM complaints ORDER BY created_at DESC").fetchall()

    # Get all staff members
    staff_members = db.execute("SELECT id, name FROM users WHERE role='staff'").fetchall()

    db.close()

    return render_template("admin_dashboard.html",
                          total_complaints=total_complaints,
                          resolved_count=resolved_count,
                          in_progress_count=in_progress_count,
                          high_priority_count=high_priority_count,
                          avg_rating=avg_rating,
                          submitted_count=submitted_count,
                          complaints=complaints,
                          staff_members=staff_members)


@app.route("/admin/assign", methods=["POST"])
def assign_staff():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/login")

    complaint_id = request.form.get("complaint_id")
    staff_id = request.form.get("staff_id")

    db = get_db()
    db.execute("UPDATE complaints SET assigned_staff_id = ? WHERE id = ?", (staff_id, complaint_id))
    db.commit()
    db.close()

    flash("✅ Staff assigned successfully!")
    return redirect("/admin")


@app.route("/admin/unassign", methods=["POST"])
def unassign_staff():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/login")

    complaint_id = request.form.get("complaint_id")

    db = get_db()
    db.execute("UPDATE complaints SET assigned_staff_id = NULL WHERE id = ?", (complaint_id,))
    db.commit()
    db.close()

    flash("❌ Staff removed successfully!")
    return redirect("/admin")


@app.route("/admin/complaint/<int:complaint_pk>/assign", methods=["POST"])
@login_required
@role_required("admin")
def assign_complaint(complaint_pk):
    staff_id = request.form.get("staff_id")
    db = get_db()
    complaint = db.execute(
        "SELECT * FROM complaints WHERE id=?", (complaint_pk,)
    ).fetchone()

    staff = db.execute(
        "SELECT * FROM users WHERE id=? AND role='staff'", (staff_id,)
    ).fetchone()

    if not complaint or not staff:
        db.close()
        abort(400)

    db.execute(
        """UPDATE complaints
           SET assigned_staff_id=?, status='Assigned', updated_at=?
           WHERE id=?""",
        (staff["id"], now(), complaint_pk)
    )
    notify(
        db, staff["id"],
        f"Complaint {complaint['complaint_id']} has been assigned to you."
    )
    notify(
        db, complaint["student_id"],
        f"Complaint {complaint['complaint_id']} has been assigned to {staff['name']}."
    )
    db.commit()
    db.close()

    flash("Complaint assigned successfully.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/complaint/<int:complaint_pk>/priority", methods=["POST"])
@login_required
@role_required("admin")
def change_priority(complaint_pk):
    priority = request.form.get("priority")
    if priority not in {"Low", "Medium", "High"}:
        abort(400)

    db = get_db()
    db.execute(
        "UPDATE complaints SET priority=?, updated_at=? WHERE id=?",
        (priority, now(), complaint_pk)
    )
    db.commit()
    db.close()
    flash("Priority updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    rows = db.execute(
        """SELECT * FROM notifications
           WHERE user_id=?
           ORDER BY created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    db.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=?",
        (session["user_id"],)
    )
    db.commit()
    db.close()
    return render_template("notifications.html", notifications=rows)


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to access this page."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="The requested page was not found."), 404


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)