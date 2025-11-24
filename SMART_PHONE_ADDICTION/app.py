from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import pickle
import os
import datetime
import ast   # needed to parse stored inputs

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

# BASE PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "addiction.db")
MODEL_PATH = os.path.join(BASE_DIR, "model", "multiple_models.pkl")

print(f"[DEBUG] Using DB_PATH: {DB_PATH}")

# Load Model (optional)
model = None
if os.path.exists(MODEL_PATH):
    try:
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
    except Exception as e:
        print("MODEL LOAD ERROR:", e)
else:
    print("MODEL NOT FOUND:", MODEL_PATH)


# ---------------------------------------------------------
#   DATABASE INITIALIZATION
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    # logs table includes category, age and weighted_total columns
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            inputs TEXT,
            prediction TEXT,
            category TEXT,
            age TEXT,
            weighted_total REAL,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------
#   AUTO ADD MISSING COLUMNS (NO MIGRATION SCRIPT NEEDED)
# ---------------------------------------------------------
def ensure_schema():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ensure logs table exists; if not, init_db() should be called first
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs';")
    if not c.fetchone():
        conn.close()
        return

    # Get current columns
    c.execute("PRAGMA table_info(logs);")
    cols = [row[1] for row in c.fetchall()]

    # Add missing columns if needed
    if "category" not in cols:
        print("[AUTO-MIGRATE] Adding 'category' column to logs table...")
        c.execute("ALTER TABLE logs ADD COLUMN category TEXT;")
        conn.commit()
        print("[AUTO-MIGRATE] 'category' added.")

    if "age" not in cols:
        print("[AUTO-MIGRATE] Adding 'age' column to logs table...")
        c.execute("ALTER TABLE logs ADD COLUMN age TEXT;")
        conn.commit()
        print("[AUTO-MIGRATE] 'age' added.")

    if "weighted_total" not in cols:
        print("[AUTO-MIGRATE] Adding 'weighted_total' column to logs table...")
        c.execute("ALTER TABLE logs ADD COLUMN weighted_total REAL;")
        conn.commit()
        print("[AUTO-MIGRATE] 'weighted_total' added.")

    conn.close()


# Run DB setup and auto-fix
init_db()
ensure_schema()


# ---------------------------------------------------------
#   WEIGHTS (match the exact order of the 18 questions)
#   Adjust these numbers if you want different importance.
# ---------------------------------------------------------
# Questions order:
# 1 Do you use your phone to click pictures of class notes?
# 2 Do you buy books/access books from your mobile?
# 3 Does your phone's battery last a day?
# 4 When your phone's battery dies out, do you run for the charger?
# 5 Do you worry about losing your cell phone?
# 6 Do you take your phone to the bathroom?
# 7 Do you check your phone immediately after waking up?
# 8 Do you use your phone while eating meals?
# 9 Do you feel anxious when your phone is not near you?
# 10 Do you spend more time on your phone than talking to people?
# 11 Do you use your phone before going to sleep?
# 12 Do you find it hard to stop using certain apps?
# 13 Do you prefer online interactions over face-to-face?
# 14 Do you use your phone during classes/lectures?
# 15 Do you get irritated when interrupted while using your phone?
# 16 Do you use your phone to escape from problems or relieve bad moods?
# 17 Do you check social media very frequently?
# 18 Do you lose track of time while using your phone?

weights = [
    1,  # Q1
    1,  # Q2
    1,  # Q3 (battery lasts)
    1,  # Q4 (run for charger)
    1,  # Q5 (worry about losing)
    1,  # Q6 (take to bathroom)
    3,  # Q7 (check after waking) - high impact
    1,  # Q8 (while eating)
    3,  # Q9 (anxiety if not near) - high impact
    2,  # Q10 (more time than talking) - medium
    3,  # Q11 (before sleep) - high
    3,  # Q12 (hard to stop certain apps) - high
    2,  # Q13 (prefer online) - medium
    2,  # Q14 (during classes) - medium
    2,  # Q15 (irritated when interrupted) - medium
    2,  # Q16 (escape from problems) - medium
    2,  # Q17 (check social media frequently) - medium
    3   # Q18 (lose track of time) - high
]

MAX_POSSIBLE_WEIGHT = sum(weights)  # used to compute percentage


# ---------------------------------------------------------
#   HELPER: STAGE DETAILS (based on percentage)
# ---------------------------------------------------------
def get_stage_details(addiction_percent):
    if addiction_percent >= 75:
        category = "Severe Addiction"
        symptoms = [
            "Constant urge to check phone (every few minutes)",
            "Neglecting important tasks, relationships or responsibilities",
            "Significant sleep disturbance (staying up late, waking at night)",
            "Using phone to escape emotions or relieve negative moods",
            "Physical symptoms: eye strain, headaches, neck/shoulder pain",
            "Marked anxiety or irritability when phone is unavailable"
        ]
        tips = [
            "Set strict daily screen-time limits (use OS tools or third-party apps)",
            "Create phone-free zones (bedroom, dining table, study area)",
            "Turn off all non-essential notifications and put phone on Do Not Disturb",
            "Charge the phone outside the bedroom overnight",
            "Use grayscale/gray mode and remove addictive apps from home screen",
            "Replace heavy phone use with structured activities (exercise, social time)",
            "Consider professional support (counselor/therapist) if affecting life"
        ]

    elif addiction_percent >= 50:
        category = "Moderate Addiction"
        symptoms = [
            "Frequent checking (every 10–20 minutes)",
            "Losing track of time while using apps",
            "Feeling irritated or restless without the phone",
            "Sometimes choosing phone over face-to-face interaction",
            "Occasional late-night scrolling affecting sleep"
        ]
        tips = [
            "Set app timers for social apps (limit to 1–2 sessions/day)",
            "Put phone on charge outside the bedroom at night",
            "Use focus techniques (Pomodoro: 25–50 min focus, 5–10 min break)",
            "Disable the most distracting lock-screen notifications",
            "Use apps like Forest or built-in Screen Time to block usage",
            "Replace short boredom-checks with quick walks, stretching or a drink"
        ]

    elif addiction_percent >= 25:
        category = "Mild Addiction"
        symptoms = [
            "Occasional overuse (phone as a quick distraction)",
            "Unlocking phone without specific purpose",
            "Short periods of scrolling before sleep (10–20 minutes)",
            "Mild FOMO (fear of missing out) or routine checking"
        ]
        tips = [
            "Turn off non-essential notifications and lock-screen previews",
            "Schedule brief phone checks (e.g., 3 set times/day)",
            "Follow a 15–30 minute 'no-phone' rule before bed",
            "Use Do Not Disturb during focused work/study sessions",
            "Keep phone out of reach during short tasks so you don't autopilot-unlock",
            "Try a short digital detox (a single evening or weekend) to reset habits"
        ]

    else:
        category = "Low Risk"
        symptoms = [
            "Generally healthy phone usage habits",
            "Phone does not significantly interrupt daily life or sleep",
            "Occasional use for convenience or information"
        ]
        tips = [
            "Maintain current healthy habits",
            "Take periodic screen breaks (20–20–20 rule for eyes)",
            "Keep using screen-time tools to monitor usage",
            "Reflect if any new app starts to creep usage up and adjust limits"
        ]

    return category, symptoms, tips


# ---------------------------------------------------------
#   ROUTES
# ---------------------------------------------------------
@app.route("/")
def home():
    return render_template("home.html", username=session.get("username"))


@app.route("/about")
def about():
    return render_template("about.html", username=session.get("username"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        hashed = generate_password_hash(password)

        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
            conn.commit()
            conn.close()
            flash("Registration successful. Please login.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.")
            return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        username_input = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE LOWER(username)=LOWER(?)", (username_input,))
        row = c.fetchone()
        conn.close()

        if not row:
            flash("User not found.")
            return redirect(url_for("login"))

        user_id, db_username, stored_pw = row

        # Password check
        if stored_pw.startswith("pbkdf2:") or stored_pw.startswith("scrypt:"):
            if check_password_hash(stored_pw, password):
                session["user_id"] = user_id
                session["username"] = db_username
                flash("Login successful.")
                return redirect(url_for("predict"))
            else:
                flash("Invalid credentials.")
                return redirect(url_for("login"))
        else:
            # Plain-text fallback → Upgrade to hashed
            if password == stored_pw:
                new_hashed = generate_password_hash(password)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET password=? WHERE id=?", (new_hashed, user_id))
                conn.commit()
                conn.close()

                session["user_id"] = user_id
                session["username"] = db_username
                flash("Login successful.")
                return redirect(url_for("predict"))

            flash("Invalid credentials.")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("home"))


# ---------------------------------------------------------
#   PREDICT
# ---------------------------------------------------------
@app.route("/predict", methods=["GET", "POST"])
def predict():

    if "user_id" not in session:
        flash("Please login first.")
        return redirect(url_for("login"))

    questions = [
        "Do you use your phone to click pictures of class notes?",
        "Do you buy books/access books from your mobile?",
        "Does your phone's battery last a day?",
        "When your phone's battery dies out, do you run for the charger?",
        "Do you worry about losing your cell phone?",
        "Do you take your phone to the bathroom?",
        "Do you check your phone immediately after waking up?",
        "Do you use your phone while eating meals?",
        "Do you feel anxious when your phone is not near you?",
        "Do you spend more time on your phone than talking to people?",
        "Do you use your phone before going to sleep?",
        "Do you find it hard to stop using certain apps?",
        "Do you prefer online interactions over face-to-face?",
        "Do you use your phone during classes/lectures?",
        "Do you get irritated when interrupted while using your phone?",
        "Do you use your phone to escape from problems or relieve bad moods?",
        "Do you check social media very frequently?",
        "Do you lose track of time while using your phone?"
    ]

    if request.method == "POST":

        # Read age from form (Option B - user enters age each time)
        age = request.form.get("age", "").strip()

        # Read raw answers (0/1)
        inputs = [int(request.form.get(f"q{i}", 0)) for i in range(18)]

        # compute weighted total
        weighted_total = 0
        for i, val in enumerate(inputs):
            w = weights[i] if i < len(weights) else 1
            weighted_total += (int(val) * w)

        # compute percentage
        try:
            percentage = round((weighted_total / MAX_POSSIBLE_WEIGHT) * 100, 2)
        except Exception:
            percentage = 0.0

        # MODEL fallback: if you have a model that outputs a probability, you may choose to blend.
        # For now we use weighted percentage as the primary metric.
        addiction_prob = percentage

        # CLASSIFY
        pred = 1 if addiction_prob >= 50 else 0
        if addiction_prob == 100:
            pred = 1
        if addiction_prob == 0:
            pred = 0

        prediction_label = "Addicted" if pred == 1 else "Not Addicted"

        # Get category, symptoms and tips using helper
        category, symptoms, tips = get_stage_details(addiction_prob)

        # SAVE LOG (store age and weighted_total)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO logs (user_id, inputs, prediction, category, age, weighted_total, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session["user_id"],
                str(inputs),
                f"{prediction_label} ({addiction_prob}%)",
                category,
                age,
                float(weighted_total),
                str(datetime.datetime.now())
            )
        )
        conn.commit()
        conn.close()

        return render_template(
            "result.html",
            result=prediction_label,
            percentage=addiction_prob,
            category=category,
            symptoms=symptoms,
            tips=tips,
            weighted_total=weighted_total,
            max_possible=MAX_POSSIBLE_WEIGHT
        )

    return render_template("predict.html", questions=enumerate(questions), username=session.get("username"))


# ---------------------------------------------------------
#   VIEW LOGS
# ---------------------------------------------------------
@app.route("/logs")
def logs():
    if "user_id" not in session:
        flash("Please login.")
        return redirect(url_for("login"))

    # same question list used when saving the logs
    questions = [
        "Do you use your phone to click pictures of class notes?",
        "Do you buy books/access books from your mobile?",
        "Does your phone's battery last a day?",
        "When your phone's battery dies out, do you run for the charger?",
        "Do you worry about losing your cell phone?",
        "Do you take your phone to the bathroom?",
        "Do you check your phone immediately after waking up?",
        "Do you use your phone while eating meals?",
        "Do you feel anxious when your phone is not near you?",
        "Do you spend more time on your phone than talking to people?",
        "Do you use your phone before going to sleep?",
        "Do you find it hard to stop using certain apps?",
        "Do you prefer online interactions over face-to-face?",
        "Do you use your phone during classes/lectures?",
        "Do you get irritated when interrupted while using your phone?",
        "Do you use your phone to escape from problems or relieve bad moods?",
        "Do you check social media very frequently?",
        "Do you lose track of time while using your phone?"
    ]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, inputs, prediction, category, age, weighted_total, timestamp FROM logs WHERE user_id=? ORDER BY id DESC",
        (session["user_id"],)
    )
    rows = c.fetchall()
    conn.close()

    logs_data = []
    for r in rows:
        log_id, inputs_str, prediction, category, age, weighted_total, timestamp = r

        # parse the stored inputs string into a list safely
        parsed_list = []
        try:
            parsed = ast.literal_eval(inputs_str)
            if isinstance(parsed, (list, tuple)):
                parsed_list = list(parsed)
        except Exception:
            parsed_list = []

        # build question-answer pairs
        qa_pairs = []
        for i, q in enumerate(questions):
            if i < len(parsed_list):
                try:
                    val = int(parsed_list[i])
                    ans = "Yes" if val == 1 else "No"
                except Exception:
                    ans = "No"
            else:
                ans = "No"
            qa_pairs.append((q, ans))

        logs_data.append({
            "id": log_id,
            "answers": qa_pairs,
            "prediction": prediction,
            "category": category,
            "age": age,
            "weighted_total": weighted_total,
            "timestamp": timestamp,
            "username": session.get("username")
        })

    return render_template("logs.html", logs=logs_data, username=session.get("username"))


# ---------------------------------------------------------
#   RUN APP
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
