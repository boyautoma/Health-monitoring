import math
from datetime import datetime, timedelta
from config import ATHLETE_PROFILE
from training_calculator import calculate_training_paces, velocity_to_pace, vdot_to_velocity, get_easy_pace_min


# --- Types de séances ---

def _easy_run(distance_km, paces):
    pace_min = get_easy_pace_min(paces)
    return {
        "session_type": "easy",
        "title": f"Footing Z2 — {distance_km} km",
        "description": (
            f"Footing en endurance fondamentale. Allure {paces['easy']['pace_fast']} - "
            f"{paces['easy']['pace_slow']}/km. FC < {ATHLETE_PROFILE['fc_footing_max']} bpm STRICT. "
            "Marcher dans les montées si la FC dépasse le plafond."
        ),
        "distance_km": distance_km,
        "duration_min": round(distance_km * pace_min),
        "target_pace": f"{paces['easy']['pace_fast']} - {paces['easy']['pace_slow']}",
        "target_hr_zone": "Z2",
    }


def _long_run(distance_km, paces):
    pace_min = get_easy_pace_min(paces)
    return {
        "session_type": "long_run",
        "title": f"Sortie longue — {distance_km} km",
        "description": (
            f"Sortie longue en endurance. Allure {paces['easy']['pace_fast']} - "
            f"{paces['easy']['pace_slow']}/km. Objectif : rester en Z2 (< {ATHLETE_PROFILE['fc_footing_max']} bpm). "
            "Emporter de l'eau si > 1h. Marcher dans les côtes si nécessaire."
        ),
        "distance_km": distance_km,
        "duration_min": round(distance_km * pace_min),
        "target_pace": f"{paces['easy']['pace_fast']} - {paces['easy']['pace_slow']}",
        "target_hr_zone": "Z2",
    }


def _interval_session(total_km, reps, effort_min, recovery_min, paces, zone="Z4"):
    warmup_km = 2.0
    cooldown_km = 1.5
    pace_min = get_easy_pace_min(paces)
    return {
        "session_type": "intervals",
        "title": f"Fractionné — {reps}x{effort_min}min Z4",
        "description": (
            f"Échauffement {warmup_km} km Z1-Z2 + "
            f"{reps}x{effort_min}min effort (allure {paces['interval']['pace_fast']} - "
            f"{paces['interval']['pace_slow']}/km, FC zone {zone}) / "
            f"{recovery_min}min trot récup + "
            f"Retour calme {cooldown_km} km Z1. "
            "Si douleur tibiale > 3/5, STOPPER la séance."
        ),
        "distance_km": total_km,
        "duration_min": round(warmup_km * pace_min + reps * (effort_min + recovery_min) + cooldown_km * (pace_min + 0.5)),
        "target_pace": f"{paces['interval']['pace_fast']} - {paces['interval']['pace_slow']}",
        "target_hr_zone": zone,
    }


def _tempo_session(total_km, tempo_km, paces):
    warmup_km = 2.0
    cooldown_km = 1.5
    pace_min = get_easy_pace_min(paces)
    # Tempo pace ~1 min/km faster than easy
    tempo_pace_min = max(pace_min - 1.0, 4.5)
    return {
        "session_type": "tempo",
        "title": f"Tempo — {tempo_km} km au seuil",
        "description": (
            f"Échauffement {warmup_km} km Z1-Z2 + "
            f"{tempo_km} km au seuil (allure {paces['threshold']['pace_fast']} - "
            f"{paces['threshold']['pace_slow']}/km, FC Z3-Z4) + "
            f"Retour calme {cooldown_km} km Z1."
        ),
        "distance_km": total_km,
        "duration_min": round(warmup_km * pace_min + tempo_km * tempo_pace_min + cooldown_km * (pace_min + 0.5)),
        "target_pace": f"{paces['threshold']['pace_fast']} - {paces['threshold']['pace_slow']}",
        "target_hr_zone": "Z3-Z4",
    }


def _fartlek_session(distance_km, paces):
    """Footing Z2 avec accélérations courtes — travail de vitesse en phase base."""
    pace_min = get_easy_pace_min(paces)
    return {
        "session_type": "intervals",
        "title": f"Fartlek — {distance_km} km",
        "description": (
            f"Échauffement 10 min Z2 ({paces['easy']['pace_fast']} - {paces['easy']['pace_slow']}/km) + "
            "8×30s accélérations progressives (monter jusqu'à allure 5K sur les dernières 10s, "
            "PAS de sprint) / 90s trot récup + Retour calme 5 min Z1. "
            f"FC échauffement < {ATHLETE_PROFILE['fc_footing_max']} bpm. "
            "Si douleur tibiale > 3/5, rester en footing Z2."
        ),
        "distance_km": distance_km,
        "duration_min": round(distance_km * pace_min),
        "target_pace": "varié",
        "target_hr_zone": "Z2-Z4",
    }


def _strength_session():
    return {
        "session_type": "strength",
        "title": "Renforcement musculaire (anti-périostite)",
        "description": (
            "30 min — Squat gobelet, fentes, pont fessier, "
            "mollets excentriques ★, toe raises ★, élastique abduction, "
            "chaise murale, step-up. "
            "★ = prioritaire pour les tibias, NE PAS SAUTER."
        ),
        "distance_km": 0,
        "duration_min": 30,
        "target_pace": None,
        "target_hr_zone": None,
    }


def _rest_day():
    return {
        "session_type": "rest",
        "title": "Repos",
        "description": "Récupération complète. Étirements légers optionnels. Glaçage tibias si besoin.",
        "distance_km": 0,
        "duration_min": 0,
        "target_pace": None,
        "target_hr_zone": None,
    }


# --- Générateur de plan : Progression générale ---

def generate_general_plan(vdot, current_weekly_km, num_weeks=8, days_per_week=3, paces=None, start_date=None):
    """Génère un plan de progression générale sur des cycles de 8 semaines."""
    if paces is None:
        paces = calculate_training_paces(vdot)
    if start_date is None:
        start_date = datetime.now()
    elif isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    sessions = []
    weekly_km = current_weekly_km

    for week in range(1, num_weeks + 1):
        phase = _get_general_phase(week, num_weeks)

        # Semaine de récupération toutes les 3 semaines
        is_recovery_week = (week % ATHLETE_PROFILE["recovery_week_interval"] == 0)
        if is_recovery_week:
            week_volume = weekly_km * (1 - ATHLETE_PROFILE["recovery_week_reduction_pct"] / 100)
            phase = "recovery"
        else:
            # Progression max 10%/semaine
            if week > 1 and not is_recovery_week:
                weekly_km = min(
                    weekly_km * (1 + ATHLETE_PROFILE["max_volume_increase_pct"] / 100),
                    weekly_km + 3  # Cap absolu de +3 km/semaine
                )
            week_volume = weekly_km

        week_sessions = _build_week(week, week_volume, phase, paces, days_per_week)
        # Ajouter scheduled_date à chaque séance
        for s in week_sessions:
            day_offset = (week - 1) * 7 + s["day_of_week"]
            s["scheduled_date"] = (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        sessions.extend(week_sessions)

    return sessions


def _get_general_phase(week, total_weeks):
    if week <= total_weeks * 0.4:
        return "base"
    elif week <= total_weeks * 0.75:
        return "build"
    else:
        return "peak"


def _build_week(week_number, weekly_km, phase, paces, days_per_week=3):
    """Construit une semaine complète (course + renforcement + repos)."""
    sessions = []

    # Répartition du volume sur les jours de course
    if days_per_week == 3:
        # Mardi: 25%, Jeudi: 30%, Samedi: 45% (sortie longue)
        day1_km = round(weekly_km * 0.25, 1)  # Mardi
        day2_km = round(weekly_km * 0.30, 1)  # Jeudi
        day3_km = round(weekly_km * 0.45, 1)  # Samedi
    elif days_per_week == 4:
        day1_km = round(weekly_km * 0.20, 1)
        day2_km = round(weekly_km * 0.25, 1)
        day3_km = round(weekly_km * 0.20, 1)
        day4_km = round(weekly_km * 0.35, 1)
    else:  # 5 jours
        day1_km = round(weekly_km * 0.15, 1)
        day2_km = round(weekly_km * 0.20, 1)
        day3_km = round(weekly_km * 0.15, 1)
        day4_km = round(weekly_km * 0.20, 1)
        day5_km = round(weekly_km * 0.30, 1)

    # Lundi = repos (day_of_week=0)
    sessions.append({**_rest_day(), "week_number": week_number, "day_of_week": 0, "phase": phase})

    # Mardi = course (day_of_week=1)
    if phase == "recovery":
        run1 = _easy_run(day1_km, paces)
    elif phase == "base":
        run1 = _easy_run(day1_km, paces)
    elif phase == "build":
        run1 = _tempo_session(day2_km, round(day2_km * 0.4, 1), paces)
    else:  # peak
        run1 = _interval_session(day2_km, 8, 1, 1.5, paces)
    sessions.append({**run1, "week_number": week_number, "day_of_week": 1, "phase": phase})

    # Mercredi = renforcement (day_of_week=2)
    sessions.append({**_strength_session(), "week_number": week_number, "day_of_week": 2, "phase": phase})

    # Jeudi = course qualité (day_of_week=3)
    if phase == "recovery":
        run2 = _easy_run(round(day2_km * 0.8, 1), paces)
    elif phase == "base":
        run2 = _fartlek_session(day2_km, paces)
    elif phase == "build":
        run2 = _interval_session(day2_km, 6, 1, 1.5, paces)
    else:  # peak
        run2 = _tempo_session(day2_km, round(day2_km * 0.5, 1), paces)
    sessions.append({**run2, "week_number": week_number, "day_of_week": 3, "phase": phase})

    # Vendredi = renforcement (day_of_week=4)
    sessions.append({**_strength_session(), "week_number": week_number, "day_of_week": 4, "phase": phase})

    # Samedi = sortie longue (day_of_week=5)
    sessions.append({**_long_run(day3_km, paces), "week_number": week_number, "day_of_week": 5, "phase": phase})

    # Dimanche = repos (day_of_week=6)
    sessions.append({**_rest_day(), "week_number": week_number, "day_of_week": 6, "phase": phase})

    return sessions


# --- Générateur de plan : Préparation course ---

RACE_CONFIGS = {
    "10k": {
        "min_weeks": 8,
        "max_weeks": 12,
        "taper_weeks": 1,
        "base_pct": 0.35,
        "build_pct": 0.40,
        "peak_pct": 0.15,
        "peak_long_run_km": 14,
        "target_weekly_km_min": 25,
    },
    "semi": {
        "min_weeks": 10,
        "max_weeks": 14,
        "taper_weeks": 2,
        "base_pct": 0.30,
        "build_pct": 0.40,
        "peak_pct": 0.15,
        "peak_long_run_km": 18,
        "target_weekly_km_min": 30,
    },
    "marathon": {
        "min_weeks": 16,
        "max_weeks": 20,
        "taper_weeks": 3,
        "base_pct": 0.30,
        "build_pct": 0.35,
        "peak_pct": 0.15,
        "peak_long_run_km": 32,
        "target_weekly_km_min": 45,
    },
}


def generate_race_plan(vdot, current_weekly_km, race_distance, race_date_str, days_per_week=3, paces=None, start_date=None):
    """Génère un plan de préparation course avec périodisation."""
    if paces is None:
        paces = calculate_training_paces(vdot)
    config = RACE_CONFIGS.get(race_distance)
    if not config:
        return []

    race_date = datetime.strptime(race_date_str, "%Y-%m-%d")
    today = datetime.now()
    if start_date is None:
        start_date = today
    elif isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    available_weeks = max(1, (race_date - today).days // 7)

    # Ajuster la durée du plan
    num_weeks = min(available_weeks, config["max_weeks"])
    num_weeks = max(num_weeks, config["min_weeks"])

    taper_weeks = config["taper_weeks"]
    training_weeks = num_weeks - taper_weeks

    # Calcul des phases
    base_weeks = max(2, round(training_weeks * config["base_pct"]))
    build_weeks = max(2, round(training_weeks * config["build_pct"]))
    peak_weeks = max(1, training_weeks - base_weeks - build_weeks)

    sessions = []
    weekly_km = current_weekly_km
    target_peak_km = config["target_weekly_km_min"]

    for week in range(1, num_weeks + 1):
        # Déterminer la phase
        if week <= base_weeks:
            phase = "base"
        elif week <= base_weeks + build_weeks:
            phase = "build"
        elif week <= base_weeks + build_weeks + peak_weeks:
            phase = "peak"
        else:
            phase = "taper"

        # Semaine de récup (sauf taper)
        is_recovery = (week % 3 == 0 and phase != "taper")

        if phase == "taper":
            # Réduction progressive
            taper_week_num = week - (base_weeks + build_weeks + peak_weeks)
            reduction = 0.25 * taper_week_num  # -25% par semaine de taper
            week_volume = weekly_km * (1 - reduction)
        elif is_recovery:
            week_volume = weekly_km * 0.75
        else:
            # Progression vers le volume cible
            if week > 1:
                weekly_km = min(
                    weekly_km * 1.10,
                    target_peak_km,
                    weekly_km + 3,
                )
            week_volume = weekly_km

        week_sessions = _build_race_week(
            week, week_volume, phase, paces, days_per_week,
            race_distance, config, is_recovery
        )
        # Ajouter scheduled_date à chaque séance
        for s in week_sessions:
            day_offset = (week - 1) * 7 + s["day_of_week"]
            s["scheduled_date"] = (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        sessions.extend(week_sessions)

    return sessions


def _build_race_week(week_number, weekly_km, phase, paces, days_per_week,
                     race_distance, config, is_recovery):
    """Construit une semaine de plan course avec spécificité."""
    sessions = []

    # Répartition
    day1_km = round(weekly_km * 0.25, 1)
    day2_km = round(weekly_km * 0.30, 1)
    day3_km = round(weekly_km * 0.45, 1)

    # Lundi = repos
    sessions.append({**_rest_day(), "week_number": week_number, "day_of_week": 0, "phase": phase})

    # Mardi = footing ou qualité (day_of_week=1)
    if is_recovery:
        run1 = _easy_run(day1_km, paces)
    elif phase == "base":
        run1 = _easy_run(day1_km, paces)
    elif phase == "build":
        if week_number % 2 == 0:
            run1 = _tempo_session(day2_km, round(day2_km * 0.4, 1), paces)
        else:
            run1 = _easy_run(day1_km, paces)
    elif phase == "peak":
        run1 = _interval_session(day2_km, 8, 1, 1.5, paces)
    else:  # taper
        run1 = _easy_run(round(day1_km * 0.7, 1), paces)
    sessions.append({**run1, "week_number": week_number, "day_of_week": 1, "phase": phase})

    # Mercredi = renforcement (réduit en taper)
    if phase == "taper":
        strength = _strength_session()
        strength["description"] += " Version allégée : 2 séries au lieu de 3."
    else:
        strength = _strength_session()
    sessions.append({**strength, "week_number": week_number, "day_of_week": 2, "phase": phase})

    # Jeudi = séance qualité (day_of_week=3)
    if is_recovery:
        run2 = _easy_run(round(day2_km * 0.8, 1), paces)
    elif phase == "base":
        run2 = _fartlek_session(day2_km, paces)
    elif phase == "build":
        run2 = _interval_session(day2_km, 6, 1, 1.5, paces)
    elif phase == "peak":
        run2 = _tempo_session(day2_km, round(day2_km * 0.5, 1), paces)
    else:  # taper
        # Petite séance au rythme cible
        taper_km = round(day2_km * 0.5, 1)
        run2 = _easy_run(taper_km, paces)
        run2["description"] += f" Inclure 3-4 km à allure cible {race_distance}."
    sessions.append({**run2, "week_number": week_number, "day_of_week": 3, "phase": phase})

    # Vendredi = renforcement
    sessions.append({**_strength_session(), "week_number": week_number, "day_of_week": 4, "phase": phase})

    # Samedi = sortie longue
    if phase == "taper":
        long_km = round(day3_km * 0.5, 1)
    else:
        # Progression de la sortie longue
        max_long = config["peak_long_run_km"]
        long_km = min(day3_km, max_long)
    sessions.append({**_long_run(long_km, paces), "week_number": week_number, "day_of_week": 5, "phase": phase})

    # Dimanche = repos
    sessions.append({**_rest_day(), "week_number": week_number, "day_of_week": 6, "phase": phase})

    return sessions


def adjust_session_for_recovery(session, recovery_score, hrv_7day_avg, paces):
    """Ajuste une séance selon le score de récupération."""
    if session["session_type"] in ("rest", "strength"):
        return session

    adjusted = dict(session)

    if recovery_score < 30:
        # Repos complet
        adjusted = _rest_day()
        adjusted["adjusted"] = 1
        adjusted["adjustment_reason"] = f"Repos — score récup {recovery_score}/100"

    elif recovery_score < 50:
        # Footing très léger
        adjusted = _easy_run(round(session.get("distance_km", 5) * 0.5, 1), paces)
        adjusted["adjusted"] = 1
        adjusted["adjustment_reason"] = f"Séance allégée — score récup {recovery_score}/100"

    elif recovery_score < 75 and session["session_type"] in ("intervals", "tempo"):
        # Remplacer qualité par footing Z2
        adjusted = _easy_run(session.get("distance_km", 6), paces)
        adjusted["adjusted"] = 1
        adjusted["adjustment_reason"] = f"Fractionné → footing Z2 — score récup {recovery_score}/100"

    # Alerte HRV spécifique
    if hrv_7day_avg is not None and hrv_7day_avg < ATHLETE_PROFILE["hrv_alert_threshold"]:
        if session["session_type"] in ("intervals", "tempo"):
            adjusted = _easy_run(session.get("distance_km", 6), paces)
            adjusted["adjusted"] = 1
            adjusted["adjustment_reason"] = (
                f"HRV basse ({hrv_7day_avg:.0f} ms < {ATHLETE_PROFILE['hrv_alert_threshold']} ms) — "
                "intensité réduite"
            )

    return adjusted


# --- Utilitaires ---

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

SESSION_COLORS = {
    "easy": "#00f19f",       # Vert WHOOP
    "long_run": "#4ea8de",   # Bleu WHOOP
    "intervals": "#ff4655",  # Rouge WHOOP
    "tempo": "#ff8c42",      # Orange WHOOP
    "strength": "#7c5cfc",   # Violet WHOOP
    "rest": "#8080a0",       # Gris clair
}

SESSION_ICONS = {
    "easy": "trending-up",
    "long_run": "map",
    "intervals": "zap",
    "tempo": "activity",
    "strength": "award",
    "rest": "coffee",
}


def get_plan_summary(sessions):
    """Génère un résumé du plan pour l'affichage."""
    weeks = {}
    for s in sessions:
        wn = s["week_number"]
        if wn not in weeks:
            weeks[wn] = {"sessions": [], "total_km": 0, "phase": s.get("phase", "")}
        weeks[wn]["sessions"].append(s)
        weeks[wn]["total_km"] += s.get("distance_km", 0) or 0

    summary = []
    for wn in sorted(weeks.keys()):
        w = weeks[wn]
        summary.append({
            "week_number": wn,
            "phase": w["phase"],
            "total_km": round(w["total_km"], 1),
            "sessions": w["sessions"],
            "run_count": sum(1 for s in w["sessions"] if s["session_type"] not in ("rest", "strength")),
            "strength_count": sum(1 for s in w["sessions"] if s["session_type"] == "strength"),
        })

    return summary
