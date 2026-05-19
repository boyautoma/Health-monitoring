#!/usr/bin/env python3
"""Sync Garmin data to JSON files for the GitHub Pages dashboard.

Runs via GitHub Actions (cron 10h + 21h Paris time) or manually.
Exports: current.json, history.json, activities.json, weekly_volumes.json
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
    data = safe_call(client.get_max_metrics, date_str)
    if data and isinstance(data, list):
        for metric in data:
            g = metric.get("generic", {})
            v = g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue")
            if v:
                return v
    return None


def fetch_training_readiness(client, date_str):
    data = safe_call(client.get_training_readiness, date_str)
    if data and isinstance(data, dict):
        return data.get("score") or data.get("trainingReadinessScore")
    return None


def fetch_day(client, date_str):
    sleep = fetch_sleep(client, date_str)
    hrv = fetch_hrv(client, date_str)
    stress = fetch_stress(client, date_str)
    rhr = fetch_rhr(client, date_str)
    tr = fetch_training_readiness(client, date_str)

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
        "stress_avg": stress.get("avg_stress") if stress else None,
        "training_readiness": tr,
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


def main():
    client = connect()
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")

    print(f"Syncing data for {date_str}...")

    today_data, sleep, hrv, stress, rhr = fetch_day(client, date_str)
    vo2max = fetch_vo2max(client, date_str)

    # --- History ---
    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path, encoding="utf-8") as f:
            history = json.load(f)

    history = [h for h in history if h.get("date") != date_str]
    history.insert(0, today_data)

    existing_dates = {h["date"] for h in history}
    for i in range(1, 31):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        if d_str in existing_dates:
            continue
        print(f"  Backfilling {d_str}...")
        try:
            day, *_ = fetch_day(client, d_str)
            history.append(day)
            time.sleep(1)
        except Exception as e:
            print(f"  Skipped {d_str}: {e}")

    history.sort(key=lambda x: x.get("date", ""), reverse=True)
    history = history[:90]

    # --- Activities (90 days running) ---
    print("Fetching activities...")
    start = today - timedelta(days=90)
    raw = safe_call(
        client.get_activities_by_date,
        start.strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
        "running",
    ) or []

    activities = []
    for act in raw:
        dist = (act.get("distance") or 0) / 1000
        dur = (act.get("duration") or 0) / 60
        spd = act.get("averageSpeed")
        pace_fmt = None
        if spd and spd > 0:
            pace_s = 1000 / spd
            m, s = divmod(int(pace_s), 60)
            pace_fmt = f"{m}:{s:02d}"

        activities.append({
            "date": act.get("startTimeLocal", "")[:10],
            "name": act.get("activityName", "Course"),
            "type": act.get("activityType", {}).get("typeKey", "running"),
            "distance_km": round(dist, 1),
            "duration_min": round(dur),
            "avg_pace": pace_fmt,
            "avg_hr": act.get("averageHR"),
            "max_hr": act.get("maxHR"),
            "calories": act.get("calories"),
        })

    # --- Weekly volumes ---
    weekly_volumes = {}
    for act in activities:
        try:
            ad = datetime.strptime(act["date"], "%Y-%m-%d")
        except ValueError:
            continue
        key = (ad - timedelta(days=ad.weekday())).strftime("%Y-%m-%d")
        weekly_volumes[key] = weekly_volumes.get(key, 0) + act["distance_km"]
    weekly_volumes = {k: round(v, 1) for k, v in sorted(weekly_volumes.items())}

    # --- Write JSON ---
    os.makedirs(DATA_DIR, exist_ok=True)

    current = {
        "last_sync": datetime.now().isoformat(),
        "date": date_str,
        "profile": {
            "vo2max": vo2max,
            "vdot": vo2max,
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
        with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

    rs = today_data["recovery_score"]
    print(f"\nSync complete: {date_str}")
    print(f"  Recovery:   {rs}/100 ({recovery_level(rs)})")
    print(f"  HRV 7j:     {today_data.get('hrv_7day_avg', 'N/A')} ms")
    print(f"  RHR:        {rhr or 'N/A'} bpm")
    print(f"  Sleep:      {today_data.get('sleep_score', 'N/A')}/100")
    print(f"  Activities: {len(activities)} (90 days)")
    print(f"  History:    {len(history)} days")


if __name__ == "__main__":
    main()
