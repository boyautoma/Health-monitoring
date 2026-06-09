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
from requests.exceptions import RetryError

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


def _is_rate_limited(exc):
    """Check if an exception is a Garmin 429 rate-limit error."""
    msg = str(exc).lower()
    return "429" in msg or "too many" in msg or "rate" in msg


# Exit code 75 = EX_TEMPFAIL (temporary failure, retry later)
EXIT_RATE_LIMITED = 75


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
            if _is_rate_limited(e):
                print(f"  RATE LIMITED by Garmin (429). Exiting immediately.")
                print(f"  DO NOT retry — each attempt extends the ban.")
                sys.exit(EXIT_RATE_LIMITED)
            print(f"  garth.resume failed: {e}")
            print("  Falling back to password login...")

    if not email or not password:
        print("ERROR: No cached tokens and GARMIN_EMAIL/GARMIN_PASSWORD not set")
        sys.exit(1)

    # Single login attempt only — retries on 429 make things worse
    try:
        print("Password login attempt...")
        client = Garmin(email, password)
        client.login()
        _save_tokens(client)
        print("Logged in successfully")
        return client
    except Exception as e:
        if _is_rate_limited(e):
            print(f"  RATE LIMITED by Garmin (429). Exiting immediately.")
            print(f"  DO NOT retry — each attempt extends the ban.")
            sys.exit(EXIT_RATE_LIMITED)
        print(f"  Login failed: {e}")
        sys.exit(1)


def safe_call(func, *args, **kwargs):
    """Call a Garmin API function with rate-limit protection."""
    for attempt in range(2):
        try:
            result = func(*args, **kwargs)
            time.sleep(0.5)  # Be gentle with Garmin's API
            return result
        except Exception as e:
            if _is_rate_limited(e):
                if attempt == 0:
                    print(f"  Rate limited on {func.__name__}, waiting 30s...")
                    time.sleep(30)
                    continue
                print(f"  RATE LIMITED by Garmin (429). Exiting to avoid ban extension.")
                sys.exit(EXIT_RATE_LIMITED)
            print(f"  Warning: {e}")
            return None
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
    baseline = summary.get("baseline") or {}
    return {
        "weekly_avg": summary.get("weeklyAvg"),
        "last_night": summary.get("lastNightAvg"),  # correct key (was "lastNight" -> always None)
        "last_night_high": summary.get("lastNight5MinHigh"),
        "status": summary.get("status"),
        "baseline_low": baseline.get("balancedLow"),
        "baseline_high": baseline.get("balancedUpper"),
    }


def fetch_stress(client, date_str):
    data = safe_call(client.get_all_day_stress, date_str)
    if not data:
        return None
    # Correct key is "avgStressLevel" (was "overallStressLevel" -> always None)
    return {"avg_stress": data.get("avgStressLevel"),
            "max_stress": data.get("maxStressLevel")}


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
    """Garmin's own Training Readiness. API returns a LIST (was read as dict -> None)."""
    data = safe_call(client.get_training_readiness, date_str)
    if isinstance(data, list) and data:
        data = data[0]
    if data and isinstance(data, dict):
        rt = data.get("recoveryTime")
        return {
            "score": data.get("score") or data.get("trainingReadinessScore"),
            "level": data.get("level"),                  # e.g. "POOR", "GOOD", "PRIME"
            "feedback": data.get("feedbackShort"),       # e.g. "TIME_TO_SLOW_DOWN"
            "recovery_time_h": round(rt / 60, 1) if rt else None,
            "acute_load": data.get("acuteLoad"),
        }
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
        training_readiness=tr.get("score") if tr else None,
    )

    return {
        "date": date_str,
        "recovery_score": score,
        "hrv_7day_avg": hrv.get("weekly_avg") if hrv else None,
        "hrv_last_night": hrv.get("last_night") if hrv else None,
        "hrv_status": hrv.get("status") if hrv else None,
        "hrv_baseline_low": hrv.get("baseline_low") if hrv else None,
        "hrv_baseline_high": hrv.get("baseline_high") if hrv else None,
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
        # Garmin's own Training Readiness (the score shown on the watch)
        "training_readiness": tr.get("score") if tr else None,
        "readiness_level": tr.get("level") if tr else None,
        "readiness_feedback": tr.get("feedback") if tr else None,
        "recovery_time_h": tr.get("recovery_time_h") if tr else None,
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
    "running": (8.0, 0.15),
    "walking": (3.0, 0.20),
    "cycling": (1.0, 0.10),
}

# Default for unknown activity types (moderate impact)
_STRESS_DEFAULT = (4.0, 0.10)


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
    # Also upgrade existing entries missing newer fields (max 14 per run).
    # This gradually backfills history (readiness/stress/hrv_last_night) over
    # several runs without hammering Garmin's API (avoids 429 rate-limit).
    upgrade_count = 0
    UPGRADE_MAX = 14
    for i in range(1, BACKFILL_DAYS + 1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        existing = history_map.get(d_str)
        # "readiness_level" key is always set after an upgrade (even if value is
        # None), so this self-limits — a day is re-fetched at most once.
        needs_upgrade = (
            existing
            and "readiness_level" not in existing
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
    # 7. VO2max / VMA / VDOT
    # =====================================================================
    # If Garmin doesn't provide VO2max, estimate from best running perf
    import math

    fc_max = ATHLETE_PROFILE["fc_max"]
    fc_repos = ATHLETE_PROFILE["fc_repos_baseline"]
    estimated_vdot = None
    estimated_vo2max = None
    vdot_source = None

    if not vo2max_today:
        best_vdot = 0
        best_vdot_src = None
        hr_estimates = []

        for act in activities:
            if act.get("type") != "running":
                continue
            dist = act.get("distance_km", 0)
            pace = act.get("avg_pace")
            avg_hr = act.get("avg_hr")
            if not pace or dist < 3:
                continue
            try:
                act_date = datetime.strptime(act["date"], "%Y-%m-%d")
                if (datetime.now() - act_date).days > 180:
                    continue
            except (ValueError, KeyError):
                continue

            parts = pace.split(":")
            pace_sec = int(parts[0]) * 60 + int(parts[1])
            time_sec = pace_sec * dist
            time_min = time_sec / 60
            dist_m = dist * 1000
            velocity = dist_m / time_min
            vo2_cost = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity

            # Method 1: Pure VDOT
            pct = (0.8 + 0.1894393 * math.exp(-0.012778 * time_min)
                   + 0.2989558 * math.exp(-0.1932605 * time_min))
            vdot = vo2_cost / pct
            if vdot > best_vdot:
                best_vdot = vdot
                best_vdot_src = f"{dist}km @ {pace}/km ({act['date']})"

            # Method 2: HR-based VO2max (only for hard efforts > 70% HRR)
            if avg_hr and avg_hr > fc_repos + 0.7 * (fc_max - fc_repos):
                hrr_pct = (avg_hr - fc_repos) / (fc_max - fc_repos)
                vo2max_hr = vo2_cost / hrr_pct
                if 25 < vo2max_hr < 70:
                    hr_estimates.append((vo2max_hr, act))

        # Choose best method
        if len(hr_estimates) >= 3:
            hr_estimates.sort(key=lambda x: x[0], reverse=True)
            idx = max(0, len(hr_estimates) // 4)
            estimated_vo2max = round(hr_estimates[idx][0], 1)
            src_act = hr_estimates[idx][1]
            vdot_source = (f"{src_act['distance_km']}km @ {src_act['avg_pace']}/km "
                           f"FC {src_act['avg_hr']} ({src_act['date']})")
            print(f"  VO2max (HR method, p75): {estimated_vo2max} ({vdot_source})")

        if best_vdot > 0:
            estimated_vdot = round(best_vdot, 1)
            print(f"  VDOT (best pace): {estimated_vdot} ({best_vdot_src})")

    # Use validated values from config as floor (interval analysis > overall pace)
    validated_vo2 = ATHLETE_PROFILE.get("validated_vo2max")
    validated_vdot = ATHLETE_PROFILE.get("validated_vdot")
    validated_source = ATHLETE_PROFILE.get("vo2max_source")

    # Pick best estimate, but never go below validated floor
    best_estimated = max(filter(None, [estimated_vo2max, estimated_vdot]), default=None)
    effective_vo2 = vo2max_today or best_estimated or validated_vo2

    if effective_vo2 and validated_vo2 and effective_vo2 <= validated_vo2:
        effective_vo2 = validated_vo2
        vdot_source = validated_source
        print(f"  Using validated VO2max floor: {validated_vo2}")

    # VDOT: prefer validated if estimated is lower
    final_vdot = estimated_vdot or validated_vdot
    if final_vdot and validated_vdot and final_vdot < validated_vdot:
        final_vdot = validated_vdot

    vma = round(effective_vo2 / 3.5, 2) if effective_vo2 else None

    # =====================================================================
    # Write JSON outputs
    # =====================================================================
    os.makedirs(DATA_DIR, exist_ok=True)

    current = {
        "last_sync": datetime.now().isoformat(),
        "date": date_str,
        "profile": {
            "vo2max": effective_vo2,
            "vma": vma,
            "vdot": final_vdot or vo2max_today,
            "vdot_source": vdot_source,
            "fc_max": ATHLETE_PROFILE["fc_max"],
            "fc_repos": ATHLETE_PROFILE["fc_repos_baseline"],
            "hrv_baseline": ATHLETE_PROFILE["hrv_baseline"],
            "hrv_alert_threshold": ATHLETE_PROFILE["hrv_alert_threshold"],
        },
        "recovery": {
            # Garmin's own Training Readiness = the headline number (what the watch shows)
            "garmin_readiness": today_data.get("training_readiness"),
            "readiness_level": today_data.get("readiness_level"),
            "readiness_feedback": today_data.get("readiness_feedback"),
            "recovery_time_h": today_data.get("recovery_time_h"),
            # Custom composite score (secondary)
            "score": today_data["recovery_score"],
            "level": recovery_level(today_data["recovery_score"]),
            "hrv_last_night": today_data.get("hrv_last_night"),
            "hrv_7day_avg": today_data.get("hrv_7day_avg"),
            "hrv_status": today_data.get("hrv_status"),
            "hrv_baseline_low": today_data.get("hrv_baseline_low"),
            "hrv_baseline_high": today_data.get("hrv_baseline_high"),
            "rhr": rhr,
            "sleep_score": today_data.get("sleep_score"),
            "sleep_duration_min": today_data.get("sleep_duration_min"),
            "deep_sleep_min": today_data.get("deep_sleep_min"),
            "light_sleep_min": today_data.get("light_sleep_min"),
            "rem_sleep_min": today_data.get("rem_sleep_min"),
            "awake_min": today_data.get("awake_min"),
            "stress_avg": today_data.get("stress_avg"),
            "max_stress": stress.get("max_stress") if stress else None,
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
