import json
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

from config import SECRET_KEY, ATHLETE_PROFILE, HR_ZONES
from database import (
    init_db, get_profile, update_profile, save_activity, get_cached_activities,
    save_recovery_log, get_recovery_history, save_plan, save_sessions,
    get_active_plan, log_strength_session, get_last_strength_session,
    get_strength_count_this_week, get_adaptation_history,
)
from gamification import calculate_gamification, get_bike_substitution
from garmin_client import GarminClient
from training_calculator import (
    vo2max_to_vdot, estimate_vdot_from_activities,
    calculate_training_paces, calculate_hr_zones,
    get_race_predictions, get_calibrated_race_predictions,
    get_current_weekly_volume, get_calibrated_paces,
)
from recovery_advisor import (
    calculate_recovery_score, get_recovery_level, get_training_adjustment,
    generate_recovery_advice, check_strength_alert,
)
from plan_generator import (
    generate_general_plan, generate_race_plan, get_plan_summary,
    adjust_session_for_recovery, DAY_NAMES, SESSION_COLORS, SESSION_ICONS,
)
from strength_program import get_program as get_strength_program, get_session_summary
from plan_adapter import adapt_plan, handle_bike_replacement

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = SECRET_KEY

garmin = GarminClient()

init_db()


# --- Filtres Jinja ---
@app.template_filter("day_name")
def day_name_filter(day_index):
    return DAY_NAMES[day_index] if 0 <= day_index < 7 else ""


@app.template_filter("session_color")
def session_color_filter(session_type):
    return SESSION_COLORS.get(session_type, "#6c757d")


@app.template_filter("session_icon")
def session_icon_filter(session_type):
    return SESSION_ICONS.get(session_type, "circle")


SESSION_COLOR_CLASSES = {
    "easy": "success",
    "long_run": "primary",
    "intervals": "danger",
    "tempo": "warning",
    "strength": "purple",
    "rest": "secondary",
}


@app.template_filter("session_color_class")
def session_color_class_filter(session_type):
    return SESSION_COLOR_CLASSES.get(session_type, "secondary")


@app.template_filter("format_duration")
def format_duration_filter(minutes):
    if not minutes:
        return "—"
    h = int(minutes) // 60
    m = int(minutes) % 60
    if h > 0:
        return f"{h}h{m:02d}"
    return f"{m} min"


@app.template_filter("format_pace")
def format_pace_filter(seconds_per_km):
    if not seconds_per_km:
        return "—"
    minutes = int(seconds_per_km) // 60
    secs = int(seconds_per_km) % 60
    return f"{minutes}:{secs:02d}/km"


# --- Routes ---

@app.route("/")
def index():
    if not garmin.is_connected():
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email et mot de passe requis.", "danger")
            return render_template("login.html")

        # Essayer de se connecter
        if garmin.login(email, password):
            update_profile(garmin_email=email, last_sync=datetime.now().isoformat())
            flash("Connecté à Garmin Connect !", "success")
            return redirect(url_for("sync_data"))
        else:
            flash("Échec de connexion. Vérifie tes identifiants Garmin.", "danger")

    # Tenter la reprise de session
    if garmin.resume_session():
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/sync")
def sync_data():
    """Synchronise les données depuis Garmin Connect."""
    if not garmin.is_connected():
        return redirect(url_for("login"))

    try:
        # Récupérer les activités récentes
        activities = garmin.get_recent_activities(weeks=8)
        for act in activities:
            save_activity(act)

        # Récupérer VO2max Garmin + calculer VDOT depuis performances réelles
        vo2max = garmin.get_vo2max()
        all_acts = get_cached_activities(limit=200)
        prof = get_profile()
        perf_vdot = estimate_vdot_from_activities(
            all_acts, fc_max=prof.get("fc_max") if prof else None
        )
        if vo2max or perf_vdot:
            update_data = {}
            if vo2max:
                update_data["vo2max"] = vo2max
            if perf_vdot:
                update_data["vdot"] = perf_vdot
            elif vo2max:
                update_data["vdot"] = vo2max_to_vdot(vo2max)
            update_profile(**update_data)

        # Récupérer les données de récupération (backfill 30 jours)
        existing = get_recovery_history(days=30)
        existing_dates = {r["date"] for r in existing}
        today = datetime.now()

        # Syncer les jours manquants + aujourd'hui (toujours rafraîchi)
        days_to_sync = []
        for i in range(30):
            d = today - timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            if i == 0 or d_str not in existing_dates:
                days_to_sync.append(d)

        for target_date in days_to_sync:
            summary = garmin.get_daily_summary(target_date)

            hrv_data = summary.get("hrv")
            sleep_data = summary.get("sleep")
            stress_data = summary.get("stress")
            rhr = summary.get("rhr")
            training_readiness = summary.get("training_readiness")

            hrv_7day = hrv_data.get("weekly_avg") if hrv_data else None
            sleep_score = sleep_data.get("score") if sleep_data else None
            sleep_duration = sleep_data.get("duration_min") if sleep_data else None
            stress_avg = stress_data.get("avg_stress") if stress_data else None

            recovery_score = calculate_recovery_score(
                hrv_7day_avg=hrv_7day,
                sleep_score=sleep_score,
                sleep_duration_min=sleep_duration,
                rhr=rhr,
                stress_avg=stress_avg,
                training_readiness=training_readiness,
            )

            advice = generate_recovery_advice(sleep_data, hrv_data, rhr, stress_data)
            save_recovery_log({
                "date": target_date.strftime("%Y-%m-%d"),
                "hrv_value": hrv_data.get("last_night") if hrv_data else None,
                "hrv_7day_avg": hrv_7day,
                "sleep_score": sleep_score,
                "sleep_duration_min": sleep_duration,
                "sleep_bedtime": sleep_data.get("bedtime") if sleep_data else None,
                "rhr": rhr,
                "stress_avg": stress_avg,
                "body_battery_start": None,
                "training_readiness": training_readiness,
                "recovery_score": recovery_score,
                "advice": advice,
            })

        # Volume hebdomadaire
        weekly_km = get_current_weekly_volume(activities)
        if weekly_km:
            update_profile(current_weekly_km=weekly_km)

        update_profile(last_sync=datetime.now().isoformat())

        # Adapter le plan d'entraînement selon les données réelles
        try:
            adapt_plan()
        except Exception as e:
            logging.error(f"Erreur adaptation plan: {e}")

        flash("Données synchronisées avec succès !", "success")

    except Exception as e:
        logging.error(f"Erreur synchronisation: {e}")
        flash(f"Erreur lors de la synchronisation : {e}", "danger")

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if not garmin.is_connected():
        return redirect(url_for("login"))

    profile = get_profile()
    activities = get_cached_activities(limit=10)
    recovery_history = get_recovery_history(days=30)
    today_recovery = recovery_history[0] if recovery_history else None

    # Score de récupération et alertes
    recovery_score = today_recovery["recovery_score"] if today_recovery else None
    recovery_level = get_recovery_level(recovery_score) if recovery_score else ("unknown", "secondary", "Pas de données")

    hrv_7day = today_recovery["hrv_7day_avg"] if today_recovery else None
    adjustment, alerts = get_training_adjustment(
        recovery_score or 50, hrv_7day
    )

    # Alerte renforcement
    last_strength = get_last_strength_session()
    strength_alert = check_strength_alert(
        last_strength["date"] if last_strength else None
    )
    if strength_alert:
        alerts.append(strength_alert)

    # Allures : calibrées depuis les données réelles, sinon VDOT théorique
    vdot = profile.get("vdot") if profile else None
    all_activities = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_activities)
    if paces is None and vdot:
        paces = calculate_training_paces(vdot)
    # Prédictions : cohérentes avec les allures affichées
    predictions = get_calibrated_race_predictions(paces)
    if not predictions and vdot:
        predictions = get_race_predictions(vdot)
    hr_zones = calculate_hr_zones(
        profile.get("fc_max") if profile else None,
        profile.get("fc_repos") if profile else None,
    )

    # Données pour les graphiques
    weekly_volumes = {}
    for act in all_activities:
        date_str = (act.get("activity_date") or "")[:10]
        if not date_str:
            continue
        try:
            act_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        week_start = act_date - timedelta(days=act_date.weekday())
        key = week_start.strftime("%d/%m")
        km = (act.get("distance_m") or 0) / 1000
        weekly_volumes[key] = weekly_volumes.get(key, 0) + round(km, 1)

    hrv_chart = [
        {"date": r["date"], "value": r["hrv_7day_avg"]}
        for r in reversed(recovery_history) if r.get("hrv_7day_avg")
    ]
    rhr_chart = [
        {"date": r["date"], "value": r["rhr"]}
        for r in reversed(recovery_history) if r.get("rhr")
    ]
    sleep_chart = [
        {"date": r["date"], "value": r["sleep_score"]}
        for r in reversed(recovery_history) if r.get("sleep_score")
    ]

    # Formater les activités
    for act in activities:
        pace = act.get("avg_pace_s_per_km")
        if pace:
            m, s = divmod(int(pace), 60)
            act["pace_formatted"] = f"{m}:{s:02d}"
        else:
            act["pace_formatted"] = "—"
        act["distance_km"] = round((act.get("distance_m") or 0) / 1000, 1)
        act["duration_formatted"] = format_duration_filter((act.get("duration_s") or 0) / 60)

    # Récap de la sortie du jour
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_activity = None
    for act in activities:
        if (act.get("activity_date") or "")[:10] == today_str:
            today_activity = act
            break

    # Séance du jour
    today_session = None
    active_plan, plan_sessions = get_active_plan()
    if active_plan and plan_sessions:
        today_dow = datetime.now().weekday()  # 0=lundi
        current_week = 1
        if active_plan.get("start_date"):
            try:
                start = datetime.strptime(active_plan["start_date"], "%Y-%m-%d")
                current_week = max(1, ((datetime.now() - start).days // 7) + 1)
            except ValueError:
                pass
        for s in plan_sessions:
            if s.get("week_number") == current_week and s.get("day_of_week") == today_dow:
                today_session = s
                # Ajuster selon récupération
                if paces and recovery_score is not None:
                    today_session = adjust_session_for_recovery(
                        today_session, recovery_score, hrv_7day, paces
                    )
                break

    # Conseils récupération
    advice = json.loads(today_recovery["advice_json"]) if today_recovery and today_recovery.get("advice_json") else []

    # Substitution vélo pour la séance du jour
    bike_sub = None
    if today_session and today_session.get("session_type") in ("easy", "long_run", "tempo", "fartlek"):
        dist = today_session.get("distance_km")
        dur = today_session.get("duration_min")
        if dist:
            bike_sub = get_bike_substitution(dist, dur)

    # Gamification
    strength_week = get_strength_count_this_week()
    gamification = calculate_gamification(
        today_recovery, recovery_history, all_activities,
        profile, ATHLETE_PROFILE, active_plan, strength_week,
        last_strength_date=last_strength["date"] if last_strength else None,
        predictions=predictions,
    )

    # Graphiques de progression (allure, distance, FC par sortie)
    pace_chart = []
    dist_chart = []
    fc_chart = []
    for act in reversed(activities):
        date_label = (act.get("activity_date") or "")[:10]
        if not date_label:
            continue
        pace_s = act.get("avg_pace_s_per_km")
        if pace_s and pace_s > 0:
            pace_chart.append({"date": date_label, "value": round(pace_s / 60, 2)})
        if act.get("distance_km"):
            dist_chart.append({"date": date_label, "value": act["distance_km"]})
        if act.get("avg_hr"):
            fc_chart.append({"date": date_label, "value": act["avg_hr"]})

    return render_template(
        "dashboard.html",
        profile=profile,
        activities=activities,
        recovery_score=recovery_score,
        recovery_level=recovery_level,
        alerts=alerts,
        paces=paces,
        predictions=predictions,
        hr_zones=hr_zones,
        vdot=vdot,
        weekly_volumes=json.dumps(weekly_volumes),
        hrv_chart=json.dumps(hrv_chart),
        rhr_chart=json.dumps(rhr_chart),
        sleep_chart=json.dumps(sleep_chart),
        hrv_alert_threshold=ATHLETE_PROFILE["hrv_alert_threshold"],
        today_recovery=today_recovery,
        recovery_history=recovery_history,
        today_session=today_session,
        today_activity=today_activity,
        advice=advice,
        pace_chart=json.dumps(pace_chart),
        dist_chart=json.dumps(dist_chart),
        fc_chart=json.dumps(fc_chart),
        gam=gamification,
        bike_sub=bike_sub,
    )


@app.route("/plan")
def plan():
    if not garmin.is_connected():
        return redirect(url_for("login"))

    profile = get_profile()
    active_plan, sessions = get_active_plan()

    if not active_plan:
        return render_template("plan.html", plan=None, weeks=[], profile=profile)

    # Récupérer le score de récupération du jour
    recovery_history = get_recovery_history(days=1)
    today_recovery = recovery_history[0] if recovery_history else None
    recovery_score = today_recovery["recovery_score"] if today_recovery else 75
    hrv_7day = today_recovery["hrv_7day_avg"] if today_recovery else None

    vdot = profile.get("vdot") or profile.get("vo2max") or 45
    all_activities = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_activities)
    if paces is None:
        paces = calculate_training_paces(vdot)

    # Ajuster les séances futures (non persistées) selon la récupération
    # Les séances passées/aujourd'hui sont déjà adaptées par adapt_plan()
    today_str = datetime.now().strftime("%Y-%m-%d")
    adjusted_sessions = []
    for s in sessions:
        sched = s.get("scheduled_date") or ""
        if sched > today_str and s["session_type"] not in ("rest", "strength"):
            adjusted = adjust_session_for_recovery(s, recovery_score, hrv_7day, paces)
            adjusted["week_number"] = s.get("week_number", adjusted.get("week_number"))
            adjusted["day_of_week"] = s.get("day_of_week", adjusted.get("day_of_week"))
            adjusted["phase"] = s.get("phase", adjusted.get("phase"))
            # Conserver les champs adaptatifs
            for key in ("scheduled_date", "completed", "missed", "matched_activity_id",
                         "actual_distance_km", "actual_duration_min", "original_distance_km",
                         "original_session_type", "adapted_at", "id"):
                if key in s:
                    adjusted[key] = s[key]
            adjusted_sessions.append(adjusted)
        else:
            adjusted_sessions.append(s)

    weeks = get_plan_summary(adjusted_sessions)

    # Historique des adaptations
    adaptations = get_adaptation_history(active_plan["id"], limit=10)

    # Déterminer la semaine actuelle
    if active_plan.get("start_date"):
        try:
            start = datetime.strptime(active_plan["start_date"], "%Y-%m-%d")
            current_week = max(1, ((datetime.now() - start).days // 7) + 1)
        except ValueError:
            current_week = 1
    else:
        current_week = 1

    return render_template(
        "plan.html",
        plan=active_plan,
        weeks=weeks,
        current_week=current_week,
        recovery_score=recovery_score,
        profile=profile,
        day_names=DAY_NAMES,
        session_colors=SESSION_COLORS,
        adaptations=adaptations,
        today_str=today_str,
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not garmin.is_connected():
        return redirect(url_for("login"))

    profile = get_profile()

    if request.method == "POST":
        mode = request.form.get("mode", "general")
        race_distance = request.form.get("race_distance")
        race_date = request.form.get("race_date")
        days_per_week = int(request.form.get("days_per_week", 3))

        # Mettre à jour les seuils personnalisés
        fc_max = request.form.get("fc_max")
        fc_repos = request.form.get("fc_repos")
        if fc_max:
            update_profile(fc_max=int(fc_max))
        if fc_repos:
            update_profile(fc_repos=int(fc_repos))

        # Générer le plan — allures calibrées depuis les données réelles si dispo
        vdot = profile.get("vdot") or profile.get("vo2max") or 45
        current_km = profile.get("current_weekly_km") or 22
        all_activities = get_cached_activities(limit=100)
        cal_paces = get_calibrated_paces(all_activities)

        start_date = datetime.now().strftime("%Y-%m-%d")
        if mode == "race" and race_distance and race_date:
            sessions = generate_race_plan(vdot, current_km, race_distance, race_date, days_per_week, paces=cal_paces, start_date=start_date)
            plan_id = save_plan({
                "mode": "race",
                "race_distance": race_distance,
                "race_date": race_date,
                "days_per_week": days_per_week,
                "start_date": start_date,
            })
        else:
            sessions = generate_general_plan(vdot, current_km, num_weeks=8, days_per_week=days_per_week, paces=cal_paces, start_date=start_date)
            plan_id = save_plan({
                "mode": "general",
                "days_per_week": days_per_week,
                "start_date": start_date,
            })

        save_sessions(plan_id, sessions)
        # Stocker le VDOT de référence pour détecter les recalibrations
        from database import get_db
        conn = get_db()
        conn.execute("UPDATE training_plan SET reference_vdot = ? WHERE id = ?", (vdot, plan_id))
        conn.commit()
        conn.close()
        flash("Plan d'entraînement généré avec succès !", "success")
        return redirect(url_for("plan"))

    return render_template("settings.html", profile=profile)


@app.route("/recovery")
def recovery():
    if not garmin.is_connected():
        return redirect(url_for("login"))

    recovery_history = get_recovery_history(days=30)
    today = recovery_history[0] if recovery_history else None

    score = today["recovery_score"] if today else None
    level = get_recovery_level(score) if score else ("unknown", "secondary", "Pas de données")

    # Conseils
    advice = json.loads(today["advice_json"]) if today and today.get("advice_json") else []

    # Données graphiques
    score_chart = [
        {"date": r["date"], "value": r["recovery_score"]}
        for r in reversed(recovery_history) if r.get("recovery_score") is not None
    ]
    hrv_chart = [
        {"date": r["date"], "value": r["hrv_7day_avg"]}
        for r in reversed(recovery_history) if r.get("hrv_7day_avg")
    ]
    sleep_chart = [
        {"date": r["date"], "value": r["sleep_score"]}
        for r in reversed(recovery_history) if r.get("sleep_score")
    ]
    rhr_chart = [
        {"date": r["date"], "value": r["rhr"]}
        for r in reversed(recovery_history) if r.get("rhr")
    ]
    stress_chart = [
        {"date": r["date"], "value": r["stress_avg"]}
        for r in reversed(recovery_history) if r.get("stress_avg")
    ]

    return render_template(
        "recovery.html",
        today=today,
        score=score,
        level=level,
        advice=advice,
        history=recovery_history,
        score_chart=json.dumps(score_chart),
        hrv_chart=json.dumps(hrv_chart),
        sleep_chart=json.dumps(sleep_chart),
        rhr_chart=json.dumps(rhr_chart),
        stress_chart=json.dumps(stress_chart),
        hrv_alert=ATHLETE_PROFILE["hrv_alert_threshold"],
        hrv_baseline=ATHLETE_PROFILE["hrv_baseline"],
    )


@app.route("/strength", methods=["GET", "POST"])
def strength():
    if not garmin.is_connected():
        return redirect(url_for("login"))

    if request.method == "POST":
        # Enregistrer une séance de renforcement
        exercises_done = request.form.getlist("exercises")
        notes = request.form.get("notes", "")
        log_strength_session(
            date=datetime.now().strftime("%Y-%m-%d"),
            completed=1,
            exercises=exercises_done,
            notes=notes,
        )
        flash("Séance de renforcement enregistrée !", "success")
        return redirect(url_for("strength"))

    # Déterminer la semaine du programme
    plan, sessions = get_active_plan()
    if plan and plan.get("start_date"):
        try:
            start = datetime.strptime(plan["start_date"], "%Y-%m-%d")
            week_num = max(1, ((datetime.now() - start).days // 7) + 1)
        except ValueError:
            week_num = 1
    else:
        week_num = 1

    program = get_strength_program(week_num)
    last_session = get_last_strength_session()
    strength_alert = check_strength_alert(last_session["date"] if last_session else None)

    return render_template(
        "strength.html",
        program=program,
        last_session=last_session,
        strength_alert=strength_alert,
        week_num=week_num,
    )


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Endpoint API pour la synchronisation (utilisé en AJAX)."""
    if not garmin.is_connected():
        return jsonify({"error": "Non connecté"}), 401
    # Rediriger vers la route sync
    return redirect(url_for("sync_data"))


@app.route("/api/bike-replace", methods=["POST"])
def api_bike_replace():
    """Détecte l'activité vélo et remplace la séance de course."""
    if not garmin.is_connected():
        return jsonify({"error": "Non connecté"}), 401

    pain_level = int(request.form.get("pain_level", 3))

    # Chercher l'activité vélo récente via Garmin
    bike_activity = garmin.get_today_cycling()

    if not bike_activity:
        flash("Aucune activité vélo détectée aujourd'hui ou hier sur Garmin.", "warning")
        return redirect(url_for("dashboard"))

    # Sauvegarder l'activité vélo dans le cache
    save_activity(bike_activity)

    # Remplacer la séance et adapter le plan
    result = handle_bike_replacement(bike_activity, pain_level=pain_level)

    if result:
        flash(
            f"Séance remplacée par vélo : {result['bike_km']} km ({result['bike_dur_min']:.0f} min) "
            f"≈ {result['run_equiv_km']} km course. "
            f"Plan adapté pour douleur {pain_level}/5.",
            "success"
        )
    else:
        flash("Pas de séance de course à remplacer aujourd'hui.", "info")

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
