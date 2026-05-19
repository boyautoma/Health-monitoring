"""AppCoach — Gamification engine."""

from datetime import datetime, timedelta


# Cibles physiologiques par objectif de course
# Semi sub-1h30 → allure 4:15/km → VDOT ~52 → VO2max ~52 → VMA ~14.9
RACE_TARGETS = {
    "semi_1h30": {
        "label": "Semi < 1h30",
        "vo2max": 52, "vma": 14.9, "vdot": 52,
        "rhr": 50, "hrv": 58, "sleep": 80,
        "weekly_km": 35, "allure_semi": "4:15",
    },
    "semi_1h40": {
        "label": "Semi < 1h40",
        "vo2max": 48, "vma": 13.7, "vdot": 48,
        "rhr": 52, "hrv": 55, "sleep": 75,
        "weekly_km": 30, "allure_semi": "4:44",
    },
    "10k_45": {
        "label": "10K < 45min",
        "vo2max": 48, "vma": 13.7, "vdot": 48,
        "rhr": 52, "hrv": 55, "sleep": 75,
        "weekly_km": 28, "allure_semi": "4:30",
    },
}

# Ratio course → vélo (même effort cardio en Z2)
# 1km course ≈ 3km vélo, ou en temps : 1h course ≈ 1h30 vélo
BIKE_RATIO_DISTANCE = 3.0  # km vélo par km course
BIKE_RATIO_TIME = 1.5      # minutes vélo par minute course


def calculate_gamification(today_recovery, recovery_history, activities,
                           profile, athlete_config, active_plan,
                           strength_sessions_week, last_strength_date=None,
                           predictions=None):
    """Calcule toutes les métriques gamifiées pour le dashboard."""

    race_target = _get_race_target(active_plan)
    status = _daily_status(today_recovery, profile, athlete_config, race_target)
    weekly = _weekly_goals(activities, profile, active_plan,
                           strength_sessions_week)
    streaks = _streaks(recovery_history)
    cardiac = _cardiac_efficiency(activities, athlete_config)
    race = _race_progress(profile, predictions, race_target)
    periostitis = _periostitis_status(activities, athlete_config,
                                       last_strength_date, strength_sessions_week)

    trends = _trends_summary(recovery_history, race_target)

    return {
        "daily_score": status["score"],
        "daily_goals": status["goals"],
        "race_target": race_target,
        "race": race,
        "weekly_goals": weekly,
        "streaks": streaks,
        "cardiac": cardiac,
        "periostitis": periostitis,
        "trends": trends,
    }


def _get_race_target(active_plan):
    """Détermine la cible de course depuis le plan actif."""
    if active_plan and active_plan.get("race_distance"):
        dist = active_plan["race_distance"].lower()
        if "semi" in dist or "half" in dist or "21" in dist:
            return RACE_TARGETS["semi_1h30"]
        if "10" in dist:
            return RACE_TARGETS["10k_45"]
    return RACE_TARGETS["semi_1h30"]  # défaut


# ── Status du jour (métriques actuelles vs cibles course) ────────────

def _daily_status(today_recovery, profile, config, race_target):
    goals = []
    weights = []

    vo2 = (profile or {}).get("vo2max")
    target_vo2 = race_target["vo2max"]
    if vo2:
        pct = min(100, round(vo2 / target_vo2 * 100))
        goals.append({
            "name": "VO2max", "value": round(vo2), "fmt": str(round(vo2)),
            "target": target_vo2, "target_fmt": str(target_vo2),
            "pct": pct, "color": "#ff4655",
        })
        weights.append((pct, 30))

    if today_recovery:
        hrv = today_recovery.get("hrv_7day_avg")
        target_hrv = race_target["hrv"]
        if hrv is not None:
            pct = min(100, max(0, round(hrv / target_hrv * 100)))
            goals.append({
                "name": "HRV 7j", "value": round(hrv), "fmt": f"{round(hrv)} ms",
                "target": target_hrv, "target_fmt": f"{target_hrv} ms",
                "pct": pct, "color": "#00d4aa",
            })
            weights.append((pct, 20))

        rhr = today_recovery.get("rhr")
        target_rhr = race_target["rhr"]
        if rhr and rhr > 0:
            pct = min(100, max(0, round(target_rhr / rhr * 100)))
            goals.append({
                "name": "FC repos", "value": rhr, "fmt": f"{rhr} bpm",
                "target": target_rhr, "target_fmt": f"\u2264 {target_rhr} bpm",
                "pct": pct, "color": "#ff8c42",
            })
            weights.append((pct, 20))

        sleep = today_recovery.get("sleep_score")
        target_sleep = race_target["sleep"]
        if sleep is not None:
            pct = min(100, round(sleep / target_sleep * 100))
            goals.append({
                "name": "Sommeil", "value": sleep, "fmt": f"{sleep}/100",
                "target": target_sleep, "target_fmt": f"\u2265 {target_sleep}",
                "pct": pct, "color": "#7c5cfc",
            })
            weights.append((pct, 15))

        stress = today_recovery.get("stress_avg")
        if stress is not None:
            pct = min(100, max(0, round((100 - stress) / 65 * 100)))
            goals.append({
                "name": "Stress", "value": stress, "fmt": f"{stress}/100",
                "target": 35, "target_fmt": "\u2264 35",
                "pct": pct, "color": "#4ea8de",
            })
            weights.append((pct, 15))

    if weights:
        total_w = sum(w for _, w in weights)
        score = round(sum(p * w for p, w in weights) / total_w)
    else:
        score = 0

    return {"score": min(100, score), "goals": goals}


# ── Progression course ────────────────────────────────────────────────

def _race_progress(profile, predictions, race_target):
    """Calcule la progression vers l'objectif de course."""
    vo2 = (profile or {}).get("vo2max")
    vma = round(vo2 / 3.5, 1) if vo2 else None

    def _pred(key):
        if not predictions:
            return None
        p = predictions.get(key)
        return p if isinstance(p, dict) else None

    semi = _pred("Semi-marathon")
    five_k = _pred("5K")
    ten_k = _pred("10K")
    marathon = _pred("Marathon")

    # Estimer le semi avec le programme suivi à la lettre
    # Approximation : +3 à +5 VDOT en 12 semaines d'entraînement structuré
    vdot_current = (profile or {}).get("vdot") or vo2
    projected_gain = 4  # VDOT points réalistes sur 12 semaines
    vdot_projected = (vdot_current + projected_gain) if vdot_current else None

    return {
        "vo2max": round(vo2) if vo2 else None,
        "vma": vma,
        "five_k": five_k,
        "ten_k": ten_k,
        "semi": semi,
        "marathon": marathon,
        "target_label": race_target["label"],
        "target_allure": race_target["allure_semi"],
        "target_vo2": race_target["vo2max"],
        "target_vma": race_target["vma"],
        "vdot_current": round(vdot_current, 1) if vdot_current else None,
        "vdot_projected": round(vdot_projected, 1) if vdot_projected else None,
        "projected_gain": projected_gain,
    }


# ── Périostites — suivi sécurité ─────────────────────────────────────

def _periostitis_status(activities, config, last_strength_date,
                         strength_count_week):
    """Tableau de bord sécurité périostites."""
    now = datetime.now()
    fc_ceiling = config.get("fc_footing_max", 155)
    max_increase = config.get("max_volume_increase_pct", 10)

    # Jours depuis dernier renfo
    days_since_strength = None
    if last_strength_date:
        try:
            if isinstance(last_strength_date, str):
                last_dt = datetime.strptime(last_strength_date[:10], "%Y-%m-%d")
            else:
                last_dt = last_strength_date
            days_since_strength = (now - last_dt).days
        except (ValueError, TypeError):
            pass

    strength_ok = strength_count_week >= 2
    strength_level = "success" if strength_ok else (
        "warning" if strength_count_week >= 1 else "danger"
    )

    # Volume semaine actuelle vs semaine précédente
    week_start = now - timedelta(days=now.weekday())
    prev_week_start = week_start - timedelta(days=7)
    ws = week_start.strftime("%Y-%m-%d")
    pws = prev_week_start.strftime("%Y-%m-%d")

    km_this_week = 0
    km_last_week = 0
    hr_violations = 0  # runs au-dessus du plafond Z2

    for act in activities:
        d = (act.get("activity_date") or "")[:10]
        km = (act.get("distance_m") or 0) / 1000
        if d >= ws:
            km_this_week += km
            if (act.get("avg_hr") or 0) > fc_ceiling:
                hr_violations += 1
        elif d >= pws:
            km_last_week += km

    km_this_week = round(km_this_week, 1)
    km_last_week = round(km_last_week, 1)

    # Progression volume sécuritaire
    safe_max = round(km_last_week * (1 + max_increase / 100), 1) if km_last_week else None
    volume_ok = (km_this_week <= safe_max) if safe_max else True
    volume_level = "success" if volume_ok else "danger"

    # Substitution vélo pour la séance du jour
    bike_sub = None

    return {
        "fc_ceiling": fc_ceiling,
        "strength_ok": strength_ok,
        "strength_level": strength_level,
        "strength_count": strength_count_week,
        "days_since_strength": days_since_strength,
        "km_this_week": km_this_week,
        "km_last_week": km_last_week,
        "safe_max_km": safe_max,
        "volume_ok": volume_ok,
        "volume_level": volume_level,
        "hr_violations": hr_violations,
        "bike_ratio": BIKE_RATIO_DISTANCE,
        "bike_time_ratio": BIKE_RATIO_TIME,
    }


def get_bike_substitution(distance_km, duration_min=None):
    """Calcule l'équivalent vélo d'une séance de course."""
    bike_km = round(distance_km * BIKE_RATIO_DISTANCE, 1)
    bike_min = round(duration_min * BIKE_RATIO_TIME) if duration_min else round(bike_km * 3)
    return {
        "distance_km": bike_km,
        "duration_min": bike_min,
        "description": f"{bike_km} km ou ~{bike_min} min en Z2 (FC < 155 bpm)",
    }


# ── Objectifs hebdomadaires ───────────────────────────────────────────

def _weekly_goals(activities, profile, active_plan, strength_count):
    goals = []
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start_str = week_start.strftime("%Y-%m-%d")

    week_acts = [
        a for a in activities
        if (a.get("activity_date") or "") >= week_start_str
    ]

    target_km = (profile or {}).get("current_weekly_km") or 22
    week_km = sum((a.get("distance_m") or 0) / 1000 for a in week_acts)
    week_km = round(week_km, 1)
    vol_pct = min(100, round(week_km / target_km * 100)) if target_km else 0
    goals.append({
        "name": "Volume", "value": week_km, "unit": "km",
        "target": target_km, "pct": vol_pct, "color": "#4ea8de",
    })

    days_target = 3
    if active_plan and active_plan.get("days_per_week"):
        days_target = active_plan["days_per_week"]
    run_count = len(week_acts)
    run_pct = min(100, round(run_count / days_target * 100)) if days_target else 0
    goals.append({
        "name": "Sorties", "value": run_count, "unit": "",
        "target": days_target, "pct": run_pct, "color": "#00f19f",
    })

    str_target = 2
    str_pct = min(100, round(strength_count / str_target * 100)) if str_target else 0
    goals.append({
        "name": "Renfo", "value": strength_count, "unit": "",
        "target": str_target, "pct": str_pct, "color": "#7c5cfc",
    })

    return goals


# ── Streaks ───────────────────────────────────────────────────────────

def _streaks(recovery_history):
    recov_streak = 0
    sleep_streak = 0

    for r in recovery_history:
        rs = r.get("recovery_score")
        if rs is not None and rs >= 60:
            recov_streak += 1
        else:
            break

    for r in recovery_history:
        ss = r.get("sleep_score")
        if ss is not None and ss >= 70:
            sleep_streak += 1
        else:
            break

    return {
        "recovery": recov_streak,
        "sleep": sleep_streak,
        "best": max(recov_streak, sleep_streak),
    }


# ── Bilan tendances (moyennes 7j gamifiées) ────────────────────────

def _rate(value, good, great):
    """Retourne un niveau : 'great', 'good', 'meh' ou 'bad'."""
    if value is None:
        return "unknown"
    if great > good:  # higher is better (HRV, sleep, recovery)
        if value >= great:
            return "great"
        if value >= good:
            return "good"
        return "bad"
    else:  # lower is better (RHR, stress)
        if value <= great:
            return "great"
        if value <= good:
            return "good"
        return "bad"


RATE_LABELS = {
    "great": {"label": "Excellent", "color": "success", "icon": "++"},
    "good": {"label": "Bien", "color": "warning", "icon": "+"},
    "bad": {"label": "A am\u00e9liorer", "color": "danger", "icon": "-"},
    "unknown": {"label": "\u2014", "color": "secondary", "icon": "?"},
}

# Conseils ciblés par métrique et par niveau
_TIPS = {
    "HRV": {
        "bad": "Priorise le repos : couche-toi 30 min plus t\u00f4t, \u00e9vite les \u00e9crans 1h avant, et r\u00e9duis l'intensit\u00e9 des s\u00e9ances cette semaine.",
        "good": "Bonne trajectoire. Maintiens la r\u00e9gularit\u00e9 du sommeil et int\u00e8gre 5 min de respiration coh\u00e9rence cardiaque le soir.",
        "great": "Continue comme \u00e7a ! Ton syst\u00e8me nerveux r\u00e9cup\u00e8re tr\u00e8s bien.",
    },
    "FC repos": {
        "bad": "Ta FC repos est haute : assure-toi d'avoir au moins 80% de tes sorties en Z2 (< 155 bpm). V\u00e9rifie hydratation et alcool.",
        "good": "En bonne voie. Plus de volume en Z2 et une bonne hydratation vont continuer \u00e0 faire baisser ta FC repos.",
        "great": "Excellent ! Ta FC repos refl\u00e8te un bon entra\u00eenement a\u00e9robie.",
    },
    "Sommeil": {
        "bad": "Score sommeil faible : vise 7h30+ de sommeil, chambre \u00e0 18-19\u00b0C, pas de caf\u00e9 apr\u00e8s 14h, routine fixe m\u00eame le week-end.",
        "good": "Pas mal ! Pour passer au niveau suivant : \u00e9vite les repas lourds le soir et bloque la lumi\u00e8re bleue 1h avant de dormir.",
        "great": "Sommeil au top ! C'est ton meilleur levier de r\u00e9cup\u00e9ration.",
    },
    "Stress": {
        "bad": "Stress \u00e9lev\u00e9 : essaie 10 min de marche en nature, respiration 3-6-5 (inspir 3s, expir 6s, 5 min), et r\u00e9duis les stimulants.",
        "good": "Stress g\u00e9rable. Garde tes habitudes de d\u00e9compression et ajoute des micro-pauses dans ta journ\u00e9e.",
        "great": "Stress tr\u00e8s bien g\u00e9r\u00e9, parfait pour la r\u00e9cup\u00e9ration et la performance.",
    },
    "R\u00e9cup\u00e9ration": {
        "bad": "R\u00e9cup insuffisante : all\u00e8ge le volume cette semaine (-20%), dors plus, et fais du v\u00e9lo en Z1 au lieu de courir.",
        "good": "Bonne r\u00e9cup. Pour optimiser : ajoute des \u00e9tirements post-run et masse tes tibias au rouleau 5 min/jour.",
        "great": "R\u00e9cup\u00e9ration optimale ! Tu peux maintenir ou augmenter l\u00e9g\u00e8rement la charge.",
    },
}


def _avg(values):
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else None


def _trends_summary(recovery_history, race_target):
    """Calcule les moyennes 7j avec rating gamifié."""
    last7 = recovery_history[:7]  # déjà trié desc (plus récent en premier)
    last30 = recovery_history[:30]

    if not last7:
        return {"metrics": [], "overall": "unknown"}

    metrics = []

    def _metric(name, avg, unit, target, rate):
        return {
            "name": name, "avg_7d": avg, "unit": unit,
            "target": target, "rate": rate,
            "tip": _TIPS.get(name, {}).get(rate, ""),
            **RATE_LABELS[rate],
        }

    # HRV 7j
    hrv_avg = _avg([r.get("hrv_7day_avg") for r in last7])
    hrv_rate = _rate(hrv_avg, race_target["hrv"] - 5, race_target["hrv"])
    metrics.append(_metric("HRV", hrv_avg, "ms", race_target["hrv"], hrv_rate))

    # FC repos
    rhr_avg = _avg([r.get("rhr") for r in last7])
    rhr_rate = _rate(rhr_avg, race_target["rhr"] + 5, race_target["rhr"])
    metrics.append(_metric("FC repos", rhr_avg, "bpm", race_target["rhr"], rhr_rate))

    # Sommeil
    sleep_avg = _avg([r.get("sleep_score") for r in last7])
    sleep_rate = _rate(sleep_avg, race_target["sleep"] - 10, race_target["sleep"])
    metrics.append(_metric("Sommeil", sleep_avg, "/100", race_target["sleep"], sleep_rate))

    # Stress
    stress_avg = _avg([r.get("stress_avg") for r in last7])
    stress_rate = _rate(stress_avg, 40, 30)
    metrics.append(_metric("Stress", stress_avg, "/100", 35, stress_rate))

    # Récupération
    recov_avg = _avg([r.get("recovery_score") for r in last7])
    recov_rate = _rate(recov_avg, 55, 70)
    metrics.append(_metric("R\u00e9cup\u00e9ration", recov_avg, "/100", 70, recov_rate))

    # Score global tendance
    rates = [m["rate"] for m in metrics if m["rate"] != "unknown"]
    great_count = rates.count("great")
    bad_count = rates.count("bad")
    if great_count >= 3:
        overall = "great"
    elif bad_count >= 3:
        overall = "bad"
    else:
        overall = "good"

    return {"metrics": metrics, "overall": overall, **RATE_LABELS[overall]}


# ── Efficacité cardiaque ─────────────────────────────────────────────

def _format_pace(seconds):
    """Convertit des secondes/km en 'M:SS'."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _cardiac_efficiency(activities, config):
    """Suit l'évolution de l'allure en Z2 : même FC, meilleure allure = progrès."""
    fc_max_z2 = config.get("fc_footing_max", 155)
    z2_runs = []

    for act in reversed(activities):
        hr = act.get("avg_hr")
        pace = act.get("avg_pace_s_per_km")
        if not hr or not pace or hr < 120 or hr > fc_max_z2 + 5:
            continue
        if pace <= 0:
            continue
        date = (act.get("activity_date") or "")[:10]
        z2_runs.append({
            "date": date,
            "pace": pace,
            "pace_fmt": _format_pace(pace),
            "hr": hr,
            "pace_min": round(pace / 60, 2),
        })

    if len(z2_runs) < 2:
        return {"runs": z2_runs, "improvement": None,
                "first_run": None, "last_run": None}

    first = z2_runs[0]
    last = z2_runs[-1]
    pace_diff = last["pace"] - first["pace"]
    pace_pct = round(-pace_diff / first["pace"] * 100, 1) if first["pace"] else 0

    return {
        "runs": z2_runs,
        "improvement": pace_pct,
        "first_run": first,
        "last_run": last,
    }
