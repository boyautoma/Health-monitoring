#!/usr/bin/env python3
"""Fetch and analyze interval splits from recent running activities
to estimate VO2max/VDOT more accurately than overall pace."""

import os, sys, json, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import garth
from garminconnect import Garmin
from sync_garmin import TOKEN_DIR, DATA_DIR, _load_json, _save_tokens

FC_MAX = 198
FC_REPOS = 53


def connect():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    try:
        garth.resume(TOKEN_DIR)
        client = Garmin()
        client.garth = garth.client
        client.display_name = garth.client.profile["displayName"]
        _save_tokens(client)
        print(f"Connected as {client.display_name}")
        return client
    except Exception as e:
        print(f"Token resume failed: {e}")
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        if not email or not password:
            print("Set GARMIN_EMAIL and GARMIN_PASSWORD")
            sys.exit(1)
        client = Garmin(email, password)
        client.login()
        _save_tokens(client)
        return client


def calc_vdot(dist_m, time_min):
    """Jack Daniels VDOT from distance (m) and time (min)."""
    velocity = dist_m / time_min  # m/min
    vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity
    pct = (0.8 + 0.1894393 * math.exp(-0.012778 * time_min)
           + 0.2989558 * math.exp(-0.1932605 * time_min))
    return vo2 / pct


def calc_vo2max_from_hr(pace_sec_per_km, avg_hr):
    """Estimate VO2max using HR-VO2 relationship (Swain).
    %HRR ~ %VO2max, so VO2max = VO2_at_pace / %HRR"""
    velocity = (1000 / pace_sec_per_km) * 60  # m/min
    vo2_at_pace = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity
    hrr_pct = (avg_hr - FC_REPOS) / (FC_MAX - FC_REPOS)
    if hrr_pct <= 0.3:
        return None  # too easy, unreliable
    return vo2_at_pace / hrr_pct


def main():
    client = connect()

    activities = _load_json(os.path.join(DATA_DIR, "activities.json"))
    # Filter running activities with HR data, sorted by date desc
    runs = [a for a in activities
            if a.get("type") == "running"
            and a.get("avg_hr")
            and a.get("distance_km", 0) >= 3]

    print(f"\nFound {len(runs)} running activities with HR data")
    print(f"Analyzing splits for the 20 most recent...\n")

    best_vdot = 0
    best_source = ""
    all_estimates = []

    for act in runs[:20]:
        act_id = act.get("activityId")
        if not act_id:
            continue

        print(f"  {act['date']} | {act['name'][:35]:35s} | {act.get('distance_km')}km | "
              f"avg HR {act.get('avg_hr')} | max HR {act.get('max_hr')}")

        try:
            splits = client.get_activity_splits(act_id)
            time.sleep(0.5)
        except Exception as e:
            print(f"    -> Error fetching splits: {e}")
            continue

        if not splits:
            print(f"    -> No splits data")
            continue

        # Parse splits - look for lap-level data
        lap_list = splits.get("lapDTOs", splits.get("laps", []))
        if not lap_list:
            # Try alternate format
            if isinstance(splits, list):
                lap_list = splits
            else:
                print(f"    -> No laps found (keys: {list(splits.keys())[:5]})")
                continue

        fast_laps = []
        for lap in lap_list:
            lap_dist = lap.get("distance", 0)  # meters
            lap_dur = lap.get("duration", 0)  # seconds
            lap_hr = lap.get("averageHR") or lap.get("averageHeartRate", 0)
            lap_max_hr = lap.get("maxHR") or lap.get("maxHeartRate", 0)
            lap_speed = lap.get("averageSpeed", 0)  # m/s

            if lap_dist < 100 or lap_dur < 30:
                continue

            pace_sec_km = (1000 / (lap_dist / lap_dur)) if lap_dist > 0 else 0
            pace_min = int(pace_sec_km // 60)
            pace_s = int(pace_sec_km % 60)

            fast_laps.append({
                "dist_m": lap_dist,
                "dur_sec": lap_dur,
                "dur_min": lap_dur / 60,
                "pace_sec_km": pace_sec_km,
                "pace_fmt": f"{pace_min}:{pace_s:02d}",
                "avg_hr": lap_hr,
                "max_hr": lap_max_hr,
            })

        if not fast_laps:
            print(f"    -> No usable laps")
            continue

        # Sort by pace (fastest first)
        fast_laps.sort(key=lambda x: x["pace_sec_km"])

        # Show all laps
        for i, lap in enumerate(fast_laps):
            marker = ""
            # Calculate VDOT for this lap
            if lap["dur_min"] >= 1:
                lap_vdot = calc_vdot(lap["dist_m"], lap["dur_min"])
                # Also estimate VO2max from HR if available
                hr_vo2 = None
                if lap["avg_hr"] and lap["avg_hr"] > 100:
                    hr_vo2 = calc_vo2max_from_hr(lap["pace_sec_km"], lap["avg_hr"])

                if lap_vdot > best_vdot and lap["dur_min"] >= 2:
                    best_vdot = lap_vdot
                    best_source = (f"{act['date']} lap {i+1}: "
                                   f"{lap['dist_m']:.0f}m in {lap['dur_sec']:.0f}s "
                                   f"@ {lap['pace_fmt']}/km HR {lap['avg_hr']}")
                    marker = " <-- BEST"

                hr_str = f" | VO2max(HR)={hr_vo2:.1f}" if hr_vo2 else ""
                print(f"      Lap {i+1}: {lap['dist_m']:.0f}m | {lap['dur_sec']:.0f}s | "
                      f"{lap['pace_fmt']}/km | HR {lap['avg_hr']}/{lap['max_hr']} | "
                      f"VDOT={lap_vdot:.1f}{hr_str}{marker}")

                if hr_vo2:
                    all_estimates.append({
                        "date": act["date"],
                        "method": "HR",
                        "vo2max": hr_vo2,
                        "lap": f"{lap['dist_m']:.0f}m @ {lap['pace_fmt']}/km HR {lap['avg_hr']}",
                    })
                all_estimates.append({
                    "date": act["date"],
                    "method": "VDOT",
                    "vo2max": lap_vdot,
                    "lap": f"{lap['dist_m']:.0f}m @ {lap['pace_fmt']}/km",
                })

        print()

    print("=" * 60)
    print(f"BEST LAP VDOT: {best_vdot:.1f}")
    print(f"  Source: {best_source}")
    vma = best_vdot / 3.5
    print(f"  VMA: {vma:.1f} km/h")

    # HR-based estimates (top 5)
    hr_estimates = sorted([e for e in all_estimates if e["method"] == "HR"],
                          key=lambda x: x["vo2max"], reverse=True)
    if hr_estimates:
        print(f"\nTop HR-based VO2max estimates:")
        for e in hr_estimates[:8]:
            print(f"  {e['date']}: VO2max={e['vo2max']:.1f} ({e['lap']})")

        # Use 75th percentile of HR-based estimates for robustness
        vals = sorted([e["vo2max"] for e in hr_estimates], reverse=True)
        p75 = vals[max(0, len(vals) // 4)]
        print(f"\n  75th percentile HR-based VO2max: {p75:.1f}")
        print(f"  VMA (HR): {p75/3.5:.1f} km/h")

    print("=" * 60)


if __name__ == "__main__":
    main()
