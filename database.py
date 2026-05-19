import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY DEFAULT 1,
            garmin_email TEXT,
            vo2max REAL,
            vdot REAL,
            fc_max INTEGER DEFAULT 198,
            fc_repos INTEGER DEFAULT 53,
            hrv_baseline REAL DEFAULT 51,
            current_weekly_km REAL DEFAULT 22,
            last_sync TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS training_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,  -- 'race' ou 'general'
            race_distance TEXT,  -- '10k', 'semi', 'marathon'
            race_date TEXT,
            days_per_week INTEGER DEFAULT 3,
            start_date TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            week_number INTEGER,
            day_of_week INTEGER,  -- 0=lundi ... 6=dimanche
            session_type TEXT,    -- 'easy', 'intervals', 'long_run', 'tempo', 'strength', 'rest'
            title TEXT,
            description TEXT,
            distance_km REAL,
            duration_min INTEGER,
            target_pace TEXT,     -- ex: "6:00-6:30"
            target_hr_zone TEXT,  -- ex: "Z2"
            phase TEXT,           -- 'base', 'build', 'peak', 'taper'
            completed INTEGER DEFAULT 0,
            adjusted INTEGER DEFAULT 0,
            adjustment_reason TEXT,
            FOREIGN KEY (plan_id) REFERENCES training_plan(id)
        );

        CREATE TABLE IF NOT EXISTS activity_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            garmin_activity_id TEXT UNIQUE,
            activity_date TEXT,
            activity_type TEXT,
            distance_m REAL,
            duration_s REAL,
            avg_hr INTEGER,
            max_hr INTEGER,
            avg_pace_s_per_km REAL,
            calories INTEGER,
            vo2max REAL,
            data_json TEXT,
            cached_at TEXT
        );

        CREATE TABLE IF NOT EXISTS recovery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            hrv_value REAL,
            hrv_7day_avg REAL,
            sleep_score INTEGER,
            sleep_duration_min INTEGER,
            sleep_bedtime TEXT,
            rhr INTEGER,
            stress_avg INTEGER,
            body_battery_start INTEGER,
            training_readiness INTEGER,
            recovery_score INTEGER,
            advice_json TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS strength_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            completed INTEGER DEFAULT 0,
            exercises_json TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS adaptation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            date TEXT,
            adaptation_type TEXT,
            description TEXT,
            details_json TEXT,
            created_at TEXT,
            FOREIGN KEY (plan_id) REFERENCES training_plan(id)
        );

        INSERT OR IGNORE INTO user_profile (id, fc_max, fc_repos, hrv_baseline, current_weekly_km)
        VALUES (1, 198, 53, 51, 22);
    """)

    # Migrations : ajouter les colonnes si elles n'existent pas
    _migrate_columns(conn, "weekly_sessions", {
        "scheduled_date": "TEXT",
        "missed": "INTEGER DEFAULT 0",
        "matched_activity_id": "TEXT",
        "actual_distance_km": "REAL",
        "actual_duration_min": "REAL",
        "original_distance_km": "REAL",
        "original_session_type": "TEXT",
        "adapted_at": "TEXT",
    })
    _migrate_columns(conn, "training_plan", {
        "reference_vdot": "REAL",
        "last_adapted_at": "TEXT",
    })

    conn.commit()
    conn.close()


def _migrate_columns(conn, table, columns):
    """Ajoute des colonnes manquantes à une table (idempotent)."""
    for col_name, col_type in columns.items():
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass  # colonne existe déjà


def get_profile():
    conn = get_db()
    row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def update_profile(**kwargs):
    conn = get_db()
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values())
    conn.execute(f"UPDATE user_profile SET {sets} WHERE id = 1", values)
    conn.commit()
    conn.close()


def save_activity(activity):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO activity_cache
        (garmin_activity_id, activity_date, activity_type, distance_m, duration_s,
         avg_hr, max_hr, avg_pace_s_per_km, calories, vo2max, data_json, cached_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(activity.get("activityId")),
        activity.get("startTimeLocal", ""),
        activity.get("activityType", {}).get("typeKey", ""),
        activity.get("distance", 0),
        activity.get("duration", 0),
        activity.get("averageHR", 0),
        activity.get("maxHR", 0),
        (1000 / activity["averageSpeed"]) if activity.get("averageSpeed") else None,
        activity.get("calories", 0),
        activity.get("vO2MaxValue"),
        json.dumps(activity),
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_cached_activities(limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity_cache ORDER BY activity_date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_recovery_log(data):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO recovery_log
        (date, hrv_value, hrv_7day_avg, sleep_score, sleep_duration_min, sleep_bedtime,
         rhr, stress_avg, body_battery_start, training_readiness, recovery_score,
         advice_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["date"],
        data.get("hrv_value"),
        data.get("hrv_7day_avg"),
        data.get("sleep_score"),
        data.get("sleep_duration_min"),
        data.get("sleep_bedtime"),
        data.get("rhr"),
        data.get("stress_avg"),
        data.get("body_battery_start"),
        data.get("training_readiness"),
        data.get("recovery_score"),
        json.dumps(data.get("advice", [])),
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_recovery_history(days=30):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM recovery_log ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_plan(plan_data):
    conn = get_db()
    # Désactiver les anciens plans
    conn.execute("UPDATE training_plan SET status = 'archived' WHERE status = 'active'")
    cursor = conn.execute("""
        INSERT INTO training_plan (mode, race_distance, race_date, days_per_week, start_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        plan_data["mode"],
        plan_data.get("race_distance"),
        plan_data.get("race_date"),
        plan_data.get("days_per_week", 3),
        plan_data.get("start_date", datetime.now().strftime("%Y-%m-%d")),
        datetime.now().isoformat(),
    ))
    plan_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return plan_id


def save_sessions(plan_id, sessions):
    conn = get_db()
    for s in sessions:
        conn.execute("""
            INSERT INTO weekly_sessions
            (plan_id, week_number, day_of_week, session_type, title, description,
             distance_km, duration_min, target_pace, target_hr_zone, phase, scheduled_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plan_id, s["week_number"], s["day_of_week"], s["session_type"],
            s["title"], s["description"], s.get("distance_km"),
            s.get("duration_min"), s.get("target_pace"), s.get("target_hr_zone"),
            s.get("phase"), s.get("scheduled_date"),
        ))
    conn.commit()
    conn.close()


def get_active_plan():
    conn = get_db()
    plan = conn.execute(
        "SELECT * FROM training_plan WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not plan:
        conn.close()
        return None, []
    sessions = conn.execute(
        "SELECT * FROM weekly_sessions WHERE plan_id = ? ORDER BY week_number, day_of_week",
        (plan["id"],)
    ).fetchall()
    conn.close()
    return dict(plan), [dict(s) for s in sessions]


def log_strength_session(date, completed, exercises, notes=""):
    conn = get_db()
    conn.execute("""
        INSERT INTO strength_log (date, completed, exercises_json, notes)
        VALUES (?, ?, ?, ?)
    """, (date, completed, json.dumps(exercises), notes))
    conn.commit()
    conn.close()


def get_last_strength_session():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM strength_log WHERE completed = 1 ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_strength_count_this_week():
    from datetime import datetime, timedelta
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM strength_log WHERE completed = 1 AND date >= ?",
        (week_start,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# --- Fonctions pour le plan adaptatif ---

def update_session(session_id, **kwargs):
    """Met à jour des colonnes arbitraires sur une session."""
    if not kwargs:
        return
    conn = get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE weekly_sessions SET {sets} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_sessions_for_date(plan_id, date_str):
    """Récupère les séances planifiées pour une date donnée."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM weekly_sessions WHERE plan_id = ? AND scheduled_date = ?",
        (plan_id, date_str)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sessions_for_week(plan_id, week_number):
    """Récupère toutes les séances d'une semaine donnée."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM weekly_sessions WHERE plan_id = ? AND week_number = ? ORDER BY day_of_week",
        (plan_id, week_number)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_adaptation_log(plan_id, adaptation_type, description, details=None):
    """Insère une entrée dans le log d'adaptation."""
    conn = get_db()
    conn.execute("""
        INSERT INTO adaptation_log (plan_id, date, adaptation_type, description, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        plan_id,
        datetime.now().strftime("%Y-%m-%d"),
        adaptation_type,
        description,
        json.dumps(details) if details else None,
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_adaptation_history(plan_id, limit=20):
    """Récupère l'historique des adaptations pour affichage."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM adaptation_log WHERE plan_id = ? ORDER BY created_at DESC LIMIT ?",
        (plan_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
