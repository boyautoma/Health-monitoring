import math
from config import ATHLETE_PROFILE, HR_ZONES
from statistics import median


def vo2max_to_vdot(vo2max):
    """Fallback si pas de performance réelle : VO2max Garmin comme VDOT."""
    return vo2max


def estimate_vdot_from_activities(activities, fc_max=None):
    """Estime le VDOT depuis la meilleure performance réelle.

    Ne retient que les courses avec effort soutenu :
    - FC moyenne >= 80% de FC max (si FC dispo), OU
    - Allure < 7:00/km (effort raisonnable, pas du footing ultra-lent)
    Parmi celles-ci, prend le meilleur VDOT implicite.
    """
    if not fc_max:
        fc_max = ATHLETE_PROFILE.get("fc_max", 198)

    best_vdot = 0
    for act in activities:
        dist_m = act.get("distance_m") or 0
        dur_s = act.get("duration_s") or 0
        avg_hr = act.get("avg_hr") or 0
        if dist_m < 3000 or dur_s < 600:
            continue

        # Filtre intensité : FC >= 80% FCmax OU allure < 420 s/km (7:00/km)
        pace_s = (dur_s / dist_m) * 1000 if dist_m > 0 else 999
        hr_ok = avg_hr >= fc_max * 0.80 if avg_hr else False
        pace_ok = pace_s < 420
        if not hr_ok and not pace_ok:
            continue

        dur_min = dur_s / 60
        vdot = race_time_to_vdot(dist_m, dur_min)
        if vdot > best_vdot:
            best_vdot = vdot
    return round(best_vdot, 1) if best_vdot > 0 else None


def race_time_to_vdot(distance_m, time_minutes):
    """Calcule le VDOT depuis un temps de course (formules de Jack Daniels)."""
    v = distance_m / time_minutes  # m/min
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v ** 2
    pct_vo2max = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * time_minutes)
        + 0.2989558 * math.exp(-0.1932605 * time_minutes)
    )
    if pct_vo2max <= 0:
        return 0
    return vo2 / pct_vo2max


def vdot_to_velocity(vdot, intensity_pct):
    """Convertit un VDOT + % d'intensité en vitesse (m/min)."""
    target_vo2 = vdot * intensity_pct
    # Résoudre: target_vo2 = -4.60 + 0.182258*v + 0.000104*v^2
    a = 0.000104
    b = 0.182258
    c = -4.60 - target_vo2
    discriminant = b ** 2 - 4 * a * c
    if discriminant < 0:
        return 0
    v = (-b + math.sqrt(discriminant)) / (2 * a)
    return max(v, 0)


def velocity_to_pace(velocity_m_per_min):
    """Convertit une vitesse (m/min) en allure (min/km)."""
    if velocity_m_per_min <= 0:
        return "N/A"
    pace_min_per_km = 1000 / velocity_m_per_min
    minutes = int(pace_min_per_km)
    seconds = int((pace_min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def format_pace_range(pace_min, pace_max):
    """Formate une plage d'allure."""
    return f"{pace_min} - {pace_max}"


def calculate_training_paces(vdot):
    """Calcule toutes les allures d'entraînement depuis le VDOT."""
    paces = {}

    # Easy: 59-74% VO2max
    v_easy_slow = vdot_to_velocity(vdot, 0.59)
    v_easy_fast = vdot_to_velocity(vdot, 0.74)
    paces["easy"] = {
        "name": "Footing (Easy)",
        "pace_slow": velocity_to_pace(v_easy_slow),
        "pace_fast": velocity_to_pace(v_easy_fast),
        "description": "Allure confortable, conversation possible",
        "hr_zone": "Z2",
        "hr_max": ATHLETE_PROFILE["fc_footing_max"],
    }

    # Marathon: 75-84% VO2max
    v_m_slow = vdot_to_velocity(vdot, 0.75)
    v_m_fast = vdot_to_velocity(vdot, 0.84)
    paces["marathon"] = {
        "name": "Marathon (M)",
        "pace_slow": velocity_to_pace(v_m_slow),
        "pace_fast": velocity_to_pace(v_m_fast),
        "description": "Allure marathon, effort modéré soutenu",
        "hr_zone": "Z3",
    }

    # Threshold: 83-88% VO2max
    v_t_slow = vdot_to_velocity(vdot, 0.83)
    v_t_fast = vdot_to_velocity(vdot, 0.88)
    paces["threshold"] = {
        "name": "Seuil (T)",
        "pace_slow": velocity_to_pace(v_t_slow),
        "pace_fast": velocity_to_pace(v_t_fast),
        "description": "Effort soutenu 20-40 min, 'confortablement dur'",
        "hr_zone": "Z3-Z4",
    }

    # Interval: 95-100% VO2max
    v_i_slow = vdot_to_velocity(vdot, 0.95)
    v_i_fast = vdot_to_velocity(vdot, 1.00)
    paces["interval"] = {
        "name": "Intervalles (I)",
        "pace_slow": velocity_to_pace(v_i_slow),
        "pace_fast": velocity_to_pace(v_i_fast),
        "description": "Efforts de 3-5 min, développe le VO2max",
        "hr_zone": "Z4-Z5",
    }

    # Repetition: >100% VO2max
    v_r = vdot_to_velocity(vdot, 1.05)
    paces["repetition"] = {
        "name": "Répétitions (R)",
        "pace_slow": velocity_to_pace(v_r),
        "pace_fast": velocity_to_pace(vdot_to_velocity(vdot, 1.10)),
        "description": "Sprints courts 200-400m, vitesse pure",
        "hr_zone": "Z5",
    }

    return paces


def calculate_hr_zones(fc_max=None, fc_repos=None):
    """Calcule les zones FC personnalisées (Karvonen)."""
    fc_max = fc_max or ATHLETE_PROFILE["fc_max"]
    fc_repos = fc_repos or ATHLETE_PROFILE["fc_repos_baseline"]
    reserve = fc_max - fc_repos

    zones = {
        "Z1": {
            "name": "Récupération",
            "min": fc_repos + int(reserve * 0.50),
            "max": fc_repos + int(reserve * 0.60),
        },
        "Z2": {
            "name": "Aérobie base",
            "min": fc_repos + int(reserve * 0.60),
            "max": ATHLETE_PROFILE["fc_footing_max"],  # Plafond strict
        },
        "Z3": {
            "name": "Tempo",
            "min": ATHLETE_PROFILE["fc_footing_max"],
            "max": fc_repos + int(reserve * 0.80),
        },
        "Z4": {
            "name": "Seuil",
            "min": fc_repos + int(reserve * 0.80),
            "max": fc_repos + int(reserve * 0.90),
        },
        "Z5": {
            "name": "Maximum",
            "min": fc_repos + int(reserve * 0.90),
            "max": fc_max,
        },
    }
    return zones


def _estimate_race_time_min(vdot, distance_m):
    """Estime un temps de course en minutes à partir du VDOT (valeur brute)."""
    low, high = 1.0, 600.0  # entre 1 min et 10h
    for _ in range(100):
        mid = (low + high) / 2
        estimated_vdot = race_time_to_vdot(distance_m, mid)
        if estimated_vdot > vdot:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _format_race_time(time_min):
    """Formate un temps en minutes vers 'Xh MM:SS' ou 'MM:SS'."""
    hours = int(time_min // 60)
    minutes = int(time_min % 60)
    seconds = int((time_min % 1) * 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def estimate_race_time(vdot, distance_m):
    """Estime un temps de course à partir du VDOT (retourne string formaté)."""
    return _format_race_time(_estimate_race_time_min(vdot, distance_m))


def get_race_predictions(vdot):
    """Prédit les temps de course pour les distances classiques.

    Retourne un dict avec temps formaté ET allure de course cohérente.
    """
    distances = {
        "5K": 5000,
        "10K": 10000,
        "Semi-marathon": 21097.5,
        "Marathon": 42195,
    }
    predictions = {}
    for name, dist_m in distances.items():
        time_min = _estimate_race_time_min(vdot, dist_m)
        dist_km = dist_m / 1000
        pace_min_per_km = time_min / dist_km
        pace_m = int(pace_min_per_km)
        pace_s = int((pace_min_per_km - pace_m) * 60)
        predictions[name] = {
            "time": _format_race_time(time_min),
            "time_min": round(time_min, 1),
            "pace": f"{pace_m}:{pace_s:02d}",
            "pace_s_per_km": round(pace_min_per_km * 60, 1),
        }
    return predictions


def _parse_pace(pace_str):
    """Parse 'M:SS' en secondes/km."""
    if not pace_str or pace_str == "N/A":
        return None
    parts = pace_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _pred_from_pace(dist_km, pace_s):
    """Construit un dict de prédiction depuis distance + allure en s/km."""
    time_min = dist_km * pace_s / 60
    pace_m = int(pace_s // 60)
    pace_sec = int(pace_s % 60)
    return {
        "time": _format_race_time(time_min),
        "time_min": round(time_min, 1),
        "pace": f"{pace_m}:{pace_sec:02d}",
        "pace_s_per_km": round(pace_s, 1),
    }


def get_calibrated_race_predictions(paces):
    """Prédit les temps de course depuis les allures calibrées (données réelles).

    Mapping JD : 5K ~ I slow, 10K ~ T fast, Semi ~ T slow, Marathon ~ M fast.
    """
    if not paces:
        return None

    # Chaque course → (distance_km, zone, extrémité)
    mapping = {
        "5K":             (5.0,     "interval",  "slow"),
        "10K":            (10.0,    "threshold", "fast"),
        "Semi-marathon":  (21.0975, "threshold", "slow"),
        "Marathon":       (42.195,  "marathon",  "fast"),
    }

    predictions = {}
    for name, (dist_km, zone, end) in mapping.items():
        if zone not in paces:
            continue
        pace_s = _parse_pace(paces[zone].get(f"pace_{end}"))
        if not pace_s:
            continue
        predictions[name] = _pred_from_pace(dist_km, pace_s)

    return predictions if predictions else None


def get_current_weekly_volume(activities):
    """Calcule le volume hebdomadaire moyen sur les 4 dernières semaines."""
    if not activities:
        return 0
    from datetime import datetime, timedelta
    four_weeks_ago = datetime.now() - timedelta(weeks=4)
    total_km = 0
    for a in activities:
        date_str = (a.get("startTimeLocal") or "")[:10]
        try:
            act_date = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if act_date >= four_weeks_ago:
            total_km += (a.get("distance", 0) or 0) / 1000
    return round(total_km / 4, 1)


def _seconds_to_pace(pace_seconds):
    """Formate des secondes/km en 'M:SS'."""
    if pace_seconds <= 0:
        return "N/A"
    pace_seconds = max(pace_seconds, 120)  # plancher à 2:00/km
    m = int(pace_seconds) // 60
    s = int(pace_seconds) % 60
    return f"{m}:{s:02d}"


def get_calibrated_paces(activities):
    """
    Calibre les allures d'entraînement depuis les données réelles (régression pace/FC).
    Utilise l'estimateur robuste de Theil-Sen.
    Retourne None si pas assez de données (< 5 activités valides).
    """
    # Filtrer les activités de course valides
    valid = []
    for a in activities:
        pace_s = a.get("avg_pace_s_per_km")
        hr = a.get("avg_hr")
        dist_m = a.get("distance_m", 0)
        # Garder : > 3km, allure 3:00-9:00/km, FC > 100
        if (pace_s and hr and 180 < pace_s < 540
                and hr > 100 and (dist_m or 0) > 3000):
            valid.append((float(pace_s), int(hr)))

    if len(valid) < 5:
        return None

    # Theil-Sen : pente médiane sur toutes les paires
    slopes = []
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            hr_diff = valid[j][1] - valid[i][1]
            if hr_diff != 0:
                slopes.append((valid[j][0] - valid[i][0]) / hr_diff)

    if not slopes:
        return None

    slope = median(slopes)

    # La pente DOIT être négative (FC haute → allure rapide = s/km plus bas)
    if slope >= 0:
        return None

    intercept = median(p - slope * hr for p, hr in valid)

    def pace_at_hr(hr):
        return slope * hr + intercept

    fc_z2_max = ATHLETE_PROFILE["fc_footing_max"]  # 155 bpm
    z3_min = HR_ZONES["Z3"]["min"]   # 155
    z4_min = HR_ZONES["Z4"]["min"]   # 169
    z4_max = HR_ZONES["Z4"]["max"]   # 184
    z5_min = HR_ZONES["Z5"]["min"]   # 184

    # Easy : cibler FC moyenne 145-155 pour rester sous le plafond Z2
    easy_fast_s = max(pace_at_hr(fc_z2_max), 360)       # le plus rapide en Z2
    easy_slow_s = min(pace_at_hr(fc_z2_max - 10), 540)  # confort ~145 bpm

    paces = {
        "easy": {
            "name": "Footing (Easy)",
            "pace_fast": _seconds_to_pace(easy_fast_s),
            "pace_slow": _seconds_to_pace(easy_slow_s),
            "description": f"Allure confortable, FC < {fc_z2_max} bpm strict",
            "hr_zone": "Z2",
            "hr_max": fc_z2_max,
        },
        "marathon": {
            "name": "Marathon (M)",
            "pace_fast": _seconds_to_pace(pace_at_hr(z3_min + 7)),
            "pace_slow": _seconds_to_pace(pace_at_hr(z3_min)),
            "description": "Allure marathon, effort modéré soutenu",
            "hr_zone": "Z3",
        },
        "threshold": {
            "name": "Seuil (T)",
            "pace_fast": _seconds_to_pace(pace_at_hr(z4_min)),
            "pace_slow": _seconds_to_pace(pace_at_hr(z3_min + 5)),
            "description": "Effort soutenu 20-40 min, 'confortablement dur'",
            "hr_zone": "Z3-Z4",
        },
        "interval": {
            "name": "Intervalles (I)",
            "pace_fast": _seconds_to_pace(pace_at_hr(z4_max - 5)),
            "pace_slow": _seconds_to_pace(pace_at_hr(z4_min)),
            "description": "Efforts de 3-5 min, développe le VO2max",
            "hr_zone": "Z4-Z5",
        },
        "repetition": {
            "name": "Répétitions (R)",
            "pace_fast": _seconds_to_pace(pace_at_hr(z5_min + 5)),
            "pace_slow": _seconds_to_pace(pace_at_hr(z5_min)),
            "description": "Sprints courts 200-400m, vitesse pure",
            "hr_zone": "Z5",
        },
    }

    return paces


def get_easy_pace_min(paces):
    """Retourne l'allure easy moyenne en minutes/km (pour estimer les durées)."""
    if not paces or "easy" not in paces:
        return 7.0  # défaut 7:00/km
    fast_str = paces["easy"]["pace_fast"]
    slow_str = paces["easy"]["pace_slow"]

    def _parse(p):
        if not p or p == "N/A":
            return 420
        parts = p.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    return (_parse(fast_str) + _parse(slow_str)) / 2 / 60
