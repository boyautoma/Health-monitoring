#!/usr/bin/env python3
"""Sync Garmin data to JSON files for the GitHub Pages dashboard.

Runs via GitHub Actions (cron 10h + 21h Paris time) or manually.
Exports: current.json, history.json, activities.json, weekly_volumes.json

Features:
- Persistent cumulative history (no 90-day cap, merges with existing data)
- Fetches ALL activity types (running, cycling, walking, etc.)
- Persistent activities store (upserts by activityId)
- Weekly volumes broken down by activity type
- Mechanical stress score per activity and per week
- VO2max history per day + VMA calculation
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta

import garth
from garminconnect import Garmin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ATHLETE_PROFILE
from recovery_advisor import calculate_recovery_score

TOKEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".garmin_tokens")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data")

# Backfill window for first run (days)
BACKFILL_DAYS = 90


def _save_tokens(client):
    try:
        client.garth.dump(TOKEN_DIR)
        print("  Tokens saved")
    except Exception as e:
        print(f"  Could not save tokens: {e}")


def connect():
    os.makedirs(TOKEN_DIR, exist_ok=True)

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    token_files = os.listdir(TOKEN_DIR) if os.path.isdir(TOKEN_DIR) else []
    if token_files:
        print(f"Found cached tokens: {token_files}")
        try:
            garth.resume(TOKEN_DIR)
            client = Garmin()
            client.garth = garth.client
            client.display_name = garth.client.profile["displayName"]
            _save_tokens(client)
            print(f"Resumed session via garth.resume (user: {garth.client.profile.get('fullName', client.display_name)})")
            return client
        except Exception as e:
            print(f"  garth.resume failed: {e}")
            print("  Falling back to password login...")

    if not email or not password:
        print("ERROR: No cached tokens and GARMIN_EMAIL/GARMIN_PASSWORD not set")
        sys.exit(1)

    for attempt in range(3):
        try:
            print(f"Password login attempt {attempt + 1}/3...")
            client = Garmin(email, password)
            client.login()
            _save_tokens(client)
            print("Logged in successfully")
            return client
        except Exception as e:
            wait = 60 * (attempt + 1)
            print(f"  Failed: {e}")
            if attempt < 2:
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)

    print("ERROR: All login attempts failed")
    sys.exit(1)


def safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"  Warning: {e}")
        return None


def _ts_to_hhmm(ts_ms):
    """Convert Garmin local timestamp (ms) to HH:MM string."""
    if not ts_ms:
        return None
    dt = datetime.fromtimestamp(ts_ms / 1000)
    return dt.strftime("%H:%M")


def fetch_sleep(client, date_str):
    data = safe_call(client.get_sleep_data, date_str)
    if not data:
        return None
    daily = data.get("dailySleepDTO", {})
    return {
        "score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
        "duration_min": (daily.get("sleepTimeSeconds") or 0) // 60,
        "deep_sleep_min": (daily.get("deepSleepSeconds") or 0) // 60,
        "light_sleep_min": (daily.get("lightSleepSeconds") or 0) // 60,
        "rem_sleep_min": (daily.get("remSleepSeconds") or 0) // 60,
        "awake_min": (daily.get("awakeSleepSeconds") or 0) // 60,
        "bedtime": _ts_to_hhmm(daily.get("sleepStartTimestampLocal")),
        "wake_time": _ts_to_hhmm(daily.get("sleepEndTimestampLocal")),
    }


def fetch_hrv(client, date_str):
    data = safe_call(client.get_hrv_data, date_str)
    if not data:
        return None
    summary = data.get("hrvSummary", {})
    return {
        "weekly_avg": summary.get("weeklyAvg"),
        "last_night": summary.get("lastNight"),
        "status": summary.get("status"),
    }


def fetch_stress(client, date_str):
    data = safe_call(client.get_all_day_stress, date_str)
    if not data:
        return None
    return {"avg_stress": data.get("overallStressLevel")}


def fetch_rhr(client, date_str):
    data = safe_call(client.get_rhr_day, date_str)
    if not data or not isinstance(data, dict):
        return None
    for entry in (
        data.get("allMetrics", {})
        .get("metricsMap", {})
        .get("WELLNESS_RESTING_HEART_RATE", [])
    ):
        if entry.get("value"):
            return int(entry["value"])
    return None


def fetch_vo2max(client, date_str):
    # Try get_max_metrics (list format)
    data = safe_call(client.get_max_metrics, date_str)
    if data:
        if isinstance(data, list):
            for metric in data:
                g = metric.get("generic", {})
                v = g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue")
                if v:
                    return v
        elif isinstance(data, dict):
            for key in ("vo2MaxPreciseValue", "vo2MaxValue"):
                if data.get(key):
                    return data[key]
            g = data.get("generic", {})
            v = g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue")
            if v:
                return v

    # Fallback: try fitness_age endpoint which sometimes includes VO2max
    data2 = safe_call(client.get_body_composition, date_str)
    if data2 and isinstance(data2, dict):
        for key in ("vo2Max", "vo2MaxValue"):
            if data2.get(key):
                return data2[key]

    return None


def fetch_training_readiness(client, date_str):
    data = safe_call(client.get_training_readiness, date_str)
    if data and isinstance(data, dict):
        return data.get("score") or data.get("trainingReadinessScore")
    return None


def fetch_day(client, date_str):
    """Fetch all wellness metrics for a single day, including VO2max."""
    sleep = fetch_sleep(client, date_str)
    hrv = fetch_hrv(client, date_str)
    stress = fetch_stress(client, date_str)
    rhr = fetch_rhr(client, date_str)
    tr = fetch_training_readiness(client, date_str)
    vo2max = fetch_vo2max(client, date_str)

    score = calculate_recovery_score(
        hrv_7day_avg=hrv.get("weekly_avg") if hrv else None,
        sleep_score=sleep.get("score") if sleep else None,
        sleep_duration_min=sleep.get("duration_min") if sleep else None,
        rhr=rhr,
        stress_avg=stress.get("avg_stress") if stress else None,
        training_readiness=tr,
    )

    return {
        "date": date_str,
        "recovery_score": score,
        "hrv_7day_avg": hrv.get("weekly_avg") if hrv else None,
        "hrv_last_night": hrv.get("last_night") if hrv else None,
        "rhr": rhr,
        "sleep_score": sleep.get("score") if sleep else None,
        "sleep_duration_min": sleep.get("duration_min") if sleep else None,
        "deep_sleep_min": sleep.get("deep_sleep_min") if sleep else None,
        "light_sleep_min": sleep.get("light_sleep_min") if sleep else None,
        "rem_sleep_min": sleep.get("rem_sleep_min") if sleep else None,
        "awake_min": sleep.get("awake_min") if sleep else None,
        "bedtime": sleep.get("bedtime") if sleep else None,
        "wake_time": sleep.get("wake_time") if sleep else None,
        "stress_avg": stress.get("avg_stress") if stress else None,
        "training_readiness": tr,
        "vo2max": vo2max,
    }, sleep, hrv, stress, rhr


def recovery_level(score):
    if score is None:
        return "unknown"
    if score >= 75:
        return "excellent"
    if score >= 50:
        return "moderate"
    if score >= 30:
        return "low"
    return "critical"


# ---------------------------------------------------------------------------
# Activity type normalization
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "running",
    "track_running": "running",
    "walking": "walking",
    "hiking": "walking",
    "cycling": "cycling",
    "road_biking": "cycling",
    "mountain_biking": "cycling",
    "indoor_cycling": "cycling",
    "virtual_ride": "cycling",
    "swimming": "swimming",
    "lap_swimming": "swimming",
    "open_water_swimming": "swimming",
    "strength_training": "strength",
    "fitness_equipment": "strength",
}


def _normalize_activity_type(raw_type_key: str) -> str:
    """Map Garmin typeKey to a simplified category."""
    return _TYPE_MAP.get(raw_type_key, raw_type_key)


# ---------------------------------------------------------------------------
# Mechanical stress
# ---------------------------------------------------------------------------

_STRESS_COEFFICIENTS = {
    # (distance_coeff, elevation_coeff)
    "running": (8.0, 0.05),
    "walking": (3.0, 0.08),
    "cycling": (1.0, 0.02),
}

# Default for unknown activity types (moderate impact)
_STRESS_DEFAULT = (4.0, 0.04)


def calc_mechanical_stress(activity_type: str, distance_km: float, elevation_gain: float) -> float:
    """Return a mechanical stress score 0-100 for a single activity."""
    dc, ec = _STRESS_COEFFICIENTS.get(activity_type, _STRESS_DEFAULT)
    raw = distance_km * dc + (elevation_gain or 0) * ec
    return min(round(raw, 1), 100.0)


# ---------------------------------------------------------------------------
# Persistent JSON helpers
# ---------------------------------------------------------------------------

def _load_json(path):
    """Load a JSON file, return [] or {} depending on content, default []."""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: could not load {path}: {e}")
    return []


def _save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    client = connect()
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")

    print(f"Syncing data for {date_str}...")

    # ----- Today's wellness data -----
    today_data, sleep, hrv, stress, rhr = fetch_day(client, date_str)
    vo2max_today = today_data.get("vo2max")

    # =====================================================================
    # 1. HISTORY: persistent cumulative, merge by date, no cap
    # =====================================================================
    history_path = os.path.join(DATA_DIR, "history.json")
    history = _load_json(history_path)

    # Build lookup by date for existing entries
    history_map = {h["date"]: h for h in history if "date" in h}

    # Upsert today
    history_map[date_str] = today_data

    # Determine which past dates need backfilling (up to BACKFILL_DAYS)
    # Also upgrade existing entries missing bedtime/wake_time (max 14 per run)
    upgrade_count = 0
    UPGRADE_MAX = 14
    for i in range(1, BACKFILL_DAYS + 1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        existing = history_map.get(d_str)
        needs_upgrade = (
            existing
            and existing.get("bedtime") is None
            and upgrade_count < UPGRADE_MAX
        )
        if existing and not needs_upgrade:
            continue
        action = "Upgrading" if needs_upgrade else "Backfilling"
        print(f"  {action} {d_str}...")
        try:
            day, *_ = fetch_day(client, d_str)
            history_map[d_str] = day
            if needs_upgrade:
                upgrade_count += 1
            time.sleep(1)
        except Exception as e:
            print(f"  Skipped {d_str}: {e}")

    # Rebuild sorted list (newest first) -- NO cap
    history = sorted(history_map.values(), key=lambda x: x.get("date", ""), reverse=True)

    # =====================================================================
    # 2 + 3. ACTIVITIES: fetch ALL types, persistent store, upsert by activityId
    # =====================================================================
    print("Fetching activities...")
    activities_path = os.path.join(DATA_DIR, "activities.json")
    existing_activities = _load_json(activities_path)

    # Build lookup by activityId (fallback: date+name)
    act_map = {}
    for a in existing_activities:
        key = a.get("activityId") or f"{a.get('date')}_{a.get('name')}"
        act_map[key] = a

    # Always fetch full BACKFILL_DAYS window (upsert by activityId ensures no dupes)
    start_dt = today - timedelta(days=BACKFILL_DAYS)

    # Fetch ALL activity types (no activitytype filter)
    raw = safe_call(
        client.get_activities_by_date,
        start_dt.strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
    ) or []

    for act in raw:
        act_id = act.get("activityId")
        raw_type = act.get("activityType", {}).get("typeKey", "other")
        norm_type = _normalize_activity_type(raw_type)

        dist = (act.get("distance") or 0) / 1000
        dur = (act.get("duration") or 0) / 60
        spd = act.get("averageSpeed")
        elev_gain = act.get("elevationGain") or 0
        elev_loss = act.get("elevationLoss") or 0

        # Pace (for running/walking)
        pace_fmt = None
        if spd and spd > 0 and norm_type in ("running", "walking"):
            pace_s = 1000 / spd
            m, s = divmod(int(pace_s), 60)
            pace_fmt = f"{m}:{s:02d}"

        # Average speed in km/h
        avg_speed_kmh = round(spd * 3.6, 1) if spd else None

        # Mechanical stress
        mech_stress = calc_mechanical_stress(norm_type, dist, elev_gain)

        entry = {
            "activityId": act_id,
            "date": act.get("startTimeLocal", "")[:10],
            "name": act.get("activityName", "Activity"),
            "type": norm_type,
            "type_raw": raw_type,
            "distance_km": round(dist, 1),
            "duration_min": round(dur),
            "avg_pace": pace_fmt,
            "avg_speed_kmh": avg_speed_kmh,
            "avg_hr": act.get("averageHR"),
            "max_hr": act.get("maxHR"),
            "calories": act.get("calories"),
            "elevation_gain": round(elev_gain, 1) if elev_gain else 0,
            "elevation_loss": round(elev_loss, 1) if elev_loss else 0,
            "training_effect_aerobic": act.get("aerobicTrainingEffect"),
            "training_effect_anaerobic": act.get("anaerobicTrainingEffect"),
            "avg_power": act.get("avgPower"),
            "mechanical_stress": mech_stress,
        }

        key = act_id or f"{entry['date']}_{entry['name']}"
        act_map[key] = entry

    # Rebuild sorted list (newest first) -- NO cap
    activities = sorted(act_map.values(), key=lambda x: x.get("date", ""), reverse=True)

    # =====================================================================
    # 4. WEEKLY VOLUMES: per activity type + total + weekly mechanical stress
    # =====================================================================
    weekly_volumes = {}
    for act in activities:
        try:
            ad = datetime.strptime(act["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        week_key = (ad - timedelta(days=ad.weekday())).strftime("%Y-%m-%d")
        if week_key not in weekly_volumes:
            weekly_volumes[week_key] = {"total": 0.0, "weekly_mechanical_stress": 0.0}

        wv = weekly_volumes[week_key]
        act_type = act.get("type", "other")
        wv[act_type] = wv.get(act_type, 0.0) + act.get("distance_km", 0)
        wv["total"] += act.get("distance_km", 0)
        wv["weekly_mechanical_stress"] += act.get("mechanical_stress", 0)

    # Round all values
    for week_key in weekly_volumes:
        wv = weekly_volumes[week_key]
        for k in wv:
            wv[k] = round(wv[k], 1)

    # Sort by week
    weekly_volumes = dict(sorted(weekly_volumes.items()))

    # =====================================================================
    # 7. VMA = VO2max / 3.5
    # =====================================================================
    vma = round(vo2max_today / 3.5, 2) if vo2max_today else None

    # =====================================================================
    # Write JSON outputs
    # =====================================================================
    os.makedirs(DATA_DIR, exist_ok=True)

    current = {
        "last_sync": datetime.now().isoformat(),
        "date": date_str,
        "profile": {
            "vo2max": vo2max_today,
            "vma": vma,
            "vdot": vo2max_today,
            "fc_max": ATHLETE_PROFILE["fc_max"],
            "fc_repos": ATHLETE_PROFILE["fc_repos_baseline"],
            "hrv_baseline": ATHLETE_PROFILE["hrv_baseline"],
            "hrv_alert_threshold": ATHLETE_PROFILE["hrv_alert_threshold"],
        },
        "recovery": {
            "score": today_data["recovery_score"],
            "level": recovery_level(today_data["recovery_score"]),
            "hrv_last_night": today_data.get("hrv_last_night"),
            "hrv_7day_avg": today_data.get("hrv_7day_avg"),
            "hrv_status": hrv.get("status") if hrv else None,
            "rhr": rhr,
            "sleep_score": today_data.get("sleep_score"),
            "sleep_duration_min": today_data.get("sleep_duration_min"),
            "deep_sleep_min": today_data.get("deep_sleep_min"),
            "light_sleep_min": today_data.get("light_sleep_min"),
            "rem_sleep_min": today_data.get("rem_sleep_min"),
            "awake_min": today_data.get("awake_min"),
            "stress_avg": today_data.get("stress_avg"),
            "training_readiness": today_data.get("training_readiness"),
        },
    }

    for name, obj in [
        ("current.json", current),
        ("history.json", history),
        ("activities.json", activities),
        ("weekly_volumes.json", weekly_volumes),
    ]:
        _save_json(os.path.join(DATA_DIR, name), obj)

    rs = today_data["recovery_score"]
    print(f"\nSync complete: {date_str}")
    print(f"  Recovery:   {rs}/100 ({recovery_level(rs)})")
    print(f"  HRV 7j:     {today_data.get('hrv_7day_avg', 'N/A')} ms")
    print(f"  RHR:        {rhr or 'N/A'} bpm")
    print(f"  Sleep:      {today_data.get('sleep_score', 'N/A')}/100")
    print(f"  VO2max:     {vo2max_today or 'N/A'} ml/kg/min")
    print(f"  VMA:        {vma or 'N/A'} km/h")
    print(f"  Activities: {len(activities)} (all time)")
    print(f"  History:    {len(history)} days")
    print(f"  Weeks:      {len(weekly_volumes)}")


if __name__ == "__main__":
    main()
