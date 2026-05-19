#!/usr/bin/env python3
"""One-time full historical fetch from Garmin Connect.

Fetches ALL wellness data (sleep, HRV, stress, RHR, VO2max) and ALL
activities since account creation. Merges with existing data files.

Usage:
    set GARMIN_EMAIL=your@email.com
    set GARMIN_PASSWORD=yourpassword
    python fetch_full_history.py
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
from sync_garmin import (
    TOKEN_DIR, DATA_DIR,
    fetch_sleep, fetch_hrv, fetch_stress, fetch_rhr,
    fetch_vo2max, fetch_training_readiness,
    calculate_recovery_score, recovery_level,
    _normalize_activity_type, calc_mechanical_stress,
    _load_json, _save_json, _save_tokens,
)

# How far back to go (days). 1825 = ~5 years.
MAX_DAYS = 1825
# Delay between API calls (seconds)
API_DELAY = 0.8


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
            print(f"Resumed session (user: {client.display_name})")
            return client
        except Exception as e:
            print(f"  garth.resume failed: {e}, falling back to password...")

    if not email or not password:
        print("ERROR: Set GARMIN_EMAIL and GARMIN_PASSWORD environment variables")
        sys.exit(1)

    print("Logging in with credentials...")
    client = Garmin(email, password)
    client.login()
    _save_tokens(client)
    print(f"Logged in as {client.display_name}")
    return client


def fetch_day_data(client, date_str):
    """Fetch all wellness metrics for one day."""
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
    }


def fetch_all_activities(client, start_date, end_date):
    """Fetch ALL activities in date range."""
    print(f"  Fetching activities from {start_date} to {end_date}...")

    all_acts = []
    # Garmin API may limit results, fetch in 90-day chunks
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while current < end:
        chunk_end = min(current + timedelta(days=90), end)
        s = current.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        print(f"    Activities {s} -> {e}...", end="", flush=True)
        try:
            raw = client.get_activities_by_date(s, e) or []
            print(f" {len(raw)} found")
            all_acts.extend(raw)
        except Exception as ex:
            print(f" ERROR: {ex}")
        time.sleep(API_DELAY)
        current = chunk_end + timedelta(days=1)

    return all_acts


def process_activity(act):
    """Convert raw Garmin activity to our format."""
    act_id = act.get("activityId")
    raw_type = act.get("activityType", {}).get("typeKey", "other")
    norm_type = _normalize_activity_type(raw_type)

    dist = (act.get("distance") or 0) / 1000
    dur = (act.get("duration") or 0) / 60
    spd = act.get("averageSpeed")
    elev_gain = act.get("elevationGain") or 0
    elev_loss = act.get("elevationLoss") or 0

    pace_fmt = None
    if spd and spd > 0 and norm_type in ("running", "walking"):
        pace_s = 1000 / spd
        m, s = divmod(int(pace_s), 60)
        pace_fmt = f"{m}:{s:02d}"

    avg_speed_kmh = round(spd * 3.6, 1) if spd else None
    mech_stress = calc_mechanical_stress(norm_type, dist, elev_gain)

    return {
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


def compute_weekly_volumes(activities):
    """Compute weekly volumes from activities list."""
    weekly = {}
    for act in activities:
        try:
            ad = datetime.strptime(act["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        week_key = (ad - timedelta(days=ad.weekday())).strftime("%Y-%m-%d")
        if week_key not in weekly:
            weekly[week_key] = {"total": 0.0, "weekly_mechanical_stress": 0.0}

        wv = weekly[week_key]
        act_type = act.get("type", "other")
        wv[act_type] = wv.get(act_type, 0.0) + act.get("distance_km", 0)
        wv["total"] += act.get("distance_km", 0)
        wv["weekly_mechanical_stress"] += act.get("mechanical_stress", 0)

    for wv in weekly.values():
        for k in wv:
            wv[k] = round(wv[k], 1)

    return dict(sorted(weekly.items()))


def main():
    client = connect()
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    start_dt = today - timedelta(days=MAX_DAYS)
    start_str = start_dt.strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"FULL HISTORICAL FETCH: {start_str} -> {today_str}")
    print(f"{'='*60}\n")

    os.makedirs(DATA_DIR, exist_ok=True)

    # ── 1. WELLNESS HISTORY ────────────────────────────────────
    history_path = os.path.join(DATA_DIR, "history.json")
    history = _load_json(history_path)
    history_map = {h["date"]: h for h in history if "date" in h}

    # Count how many days need fetching
    days_to_fetch = []
    for i in range(MAX_DAYS + 1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        existing = history_map.get(d_str)
        # Fetch if missing, or if missing bedtime (upgrade)
        if not existing or existing.get("bedtime") is None:
            days_to_fetch.append(d_str)

    total = len(days_to_fetch)
    print(f"Wellness data: {total} days to fetch/upgrade ({len(history_map)} already cached)\n")

    empty_streak = 0
    fetched = 0
    for d_str in days_to_fetch:
        fetched += 1
        pct = (fetched / total * 100) if total else 100
        print(f"  [{fetched}/{total} {pct:.0f}%] {d_str}...", end="", flush=True)

        try:
            day = fetch_day_data(client, d_str)

            # Check if this day has any actual data
            has_data = any(
                day.get(k) is not None
                for k in ("sleep_score", "hrv_7day_avg", "rhr", "stress_avg")
            )

            if has_data:
                history_map[d_str] = day
                empty_streak = 0
                print(f" OK (sleep:{day.get('sleep_score')}, hrv:{day.get('hrv_7day_avg')})")
            else:
                # Keep existing data if we had some
                if d_str in history_map:
                    print(" no new data (keeping existing)")
                else:
                    empty_streak += 1
                    print(" empty")

            time.sleep(API_DELAY)
        except Exception as e:
            print(f" ERROR: {e}")
            time.sleep(2)

        # Stop if we hit 14 consecutive empty days (likely before account/watch)
        if empty_streak >= 14:
            print(f"\n  -> 14 consecutive empty days, stopping backfill at {d_str}")
            break

        # Save progress every 50 days
        if fetched % 50 == 0:
            history = sorted(history_map.values(), key=lambda x: x.get("date", ""), reverse=True)
            _save_json(history_path, history)
            print(f"    [checkpoint saved: {len(history)} entries]")

    # Final save
    history = sorted(history_map.values(), key=lambda x: x.get("date", ""), reverse=True)
    _save_json(history_path, history)
    print(f"\n[OK] History: {len(history)} days saved")

    # ── 2. ALL ACTIVITIES ──────────────────────────────────────
    print(f"\n{'─'*40}")
    activities_path = os.path.join(DATA_DIR, "activities.json")
    existing_acts = _load_json(activities_path)
    act_map = {}
    for a in existing_acts:
        key = a.get("activityId") or f"{a.get('date')}_{a.get('name')}"
        act_map[key] = a

    raw_acts = fetch_all_activities(client, start_str, today_str)

    for act in raw_acts:
        entry = process_activity(act)
        key = entry["activityId"] or f"{entry['date']}_{entry['name']}"
        act_map[key] = entry

    activities = sorted(act_map.values(), key=lambda x: x.get("date", ""), reverse=True)
    _save_json(activities_path, activities)
    print(f"\n[OK] Activities: {len(activities)} total")

    # Count by type
    type_counts = {}
    for a in activities:
        t = a.get("type", "other")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")

    # ── 3. WEEKLY VOLUMES ──────────────────────────────────────
    weekly_volumes = compute_weekly_volumes(activities)
    _save_json(os.path.join(DATA_DIR, "weekly_volumes.json"), weekly_volumes)
    print(f"\n[OK] Weekly volumes: {len(weekly_volumes)} weeks")

    # ── 4. CURRENT.JSON ────────────────────────────────────────
    today_data = history_map.get(today_str, {})
    vo2max_today = today_data.get("vo2max")
    vma = round(vo2max_today / 3.5, 2) if vo2max_today else None

    current = {
        "last_sync": datetime.now().isoformat(),
        "date": today_str,
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
            "score": today_data.get("recovery_score"),
            "level": recovery_level(today_data.get("recovery_score")),
            "hrv_last_night": today_data.get("hrv_last_night"),
            "hrv_7day_avg": today_data.get("hrv_7day_avg"),
            "rhr": today_data.get("rhr"),
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
    _save_json(os.path.join(DATA_DIR, "current.json"), current)
    print(f"\n[OK] current.json updated")

    print(f"\n{'='*60}")
    print(f"DONE! All data saved to {DATA_DIR}")
    print(f"  {len(history)} days of wellness data")
    print(f"  {len(activities)} activities")
    print(f"  {len(weekly_volumes)} weeks of volume data")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
