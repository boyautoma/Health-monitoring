"""AppCoach — Moteur d'adaptation du plan d'entraînement.

Appelé après chaque sync Garmin pour ajuster les séances futures
en fonction des activités réalisées, de la récupération et de la forme.
"""

import logging
from datetime import datetime, timedelta

from config import ATHLETE_PROFILE
from gamification import BIKE_RATIO_DISTANCE, BIKE_RATIO_TIME
from database import (
    get_active_plan, get_cached_activities, get_recovery_history,
    get_profile, update_session, get_sessions_for_week,
    save_adaptation_log, get_db,
)
from plan_generator import (
    _easy_run, _long_run, _interval_session, _tempo_session,
    _fartlek_session, _strength_session, _rest_day,
    adjust_session_for_recovery, _build_week, _get_general_phase,
)
from training_calculator import (
    calculate_training_paces, get_calibrated_paces,
)

logger = logging.getLogger(__name__)

RUNNING_TYPES = {"easy", "long_run", "intervals", "tempo", "fartlek"}


def adapt_plan():
    """Point d'entrée principal. Appelé depuis app.py après chaque sync."""
    plan, sessions = get_active_plan()
    if not plan or not sessions:
        return

    plan_id = plan["id"]
    start_date_str = plan.get("start_date")
    if not start_date_str:
        return

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today.strftime("%Y-%m-%d")

    # 1. S'assurer que toutes les séances ont une scheduled_date
    _ensure_scheduled_dates(plan_id, sessions, start_date)

    # Recharger les sessions avec les dates mises à jour
    plan, sessions = get_active_plan()

    # 2. Charger les activités et la récupération
    activities = get_cached_activities(limit=200)
    recovery_history = get_recovery_history(days=7)
    profile = get_profile()

    # 3. Matcher les activités aux séances passées
    _match_activities_to_sessions(plan_id, sessions, activities, today_str)

    # 4. Détecter les séances manquées
    _detect_missed_sessions(plan_id, sessions, today_str)

    # 5. Déterminer la semaine courante
    current_week = max(1, ((today - start_date).days // 7) + 1)
    total_weeks = max(s["week_number"] for s in sessions)

    # 6. Ajuster le volume de la semaine suivante
    if current_week < total_weeks:
        _adjust_next_week_volume(plan_id, current_week, sessions, activities, profile)

    # 7. Recalibration VDOT si nécessaire
    _check_vdot_recalibration(plan_id, plan, sessions, profile, today_str)

    # 8. Ajustements récupération pour aujourd'hui et demain
    today_recovery = recovery_history[0] if recovery_history else None
    if today_recovery:
        _apply_recovery_adjustments(
            plan_id, sessions, today_str, today_recovery, profile
        )

    # 9. Marquer le plan comme adapté
    conn = get_db()
    conn.execute(
        "UPDATE training_plan SET last_adapted_at = ? WHERE id = ?",
        (datetime.now().isoformat(), plan_id)
    )
    conn.commit()
    conn.close()

    logger.info(f"Plan {plan_id} adapté avec succès")


def _ensure_scheduled_dates(plan_id, sessions, start_date):
    """Remplit scheduled_date pour les séances qui n'en ont pas."""
    for s in sessions:
        if not s.get("scheduled_date"):
            day_offset = (s["week_number"] - 1) * 7 + s["day_of_week"]
            scheduled = (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            update_session(s["id"], scheduled_date=scheduled)


def _match_activities_to_sessions(plan_id, sessions, activities, today_str):
    """Matche les activités Garmin aux séances planifiées par date et type."""
    # Index des activités par date
    acts_by_date = {}
    for act in activities:
        act_date = (act.get("activity_date") or "")[:10]
        if act_date:
            acts_by_date.setdefault(act_date, []).append(act)

    for s in sessions:
        # Ignorer les séances déjà matchées, futures, ou repos
        if s.get("matched_activity_id") or s.get("completed"):
            continue
        if s["session_type"] == "rest":
            continue
        sched = s.get("scheduled_date")
        if not sched or sched >= today_str:
            continue

        # Chercher une activité sur cette date (±1 jour)
        best_match = _find_best_activity(s, acts_by_date, sched)
        if best_match:
            act_dist = (best_match.get("distance_m") or 0) / 1000
            act_dur = (best_match.get("duration_s") or 0) / 60
            update_session(
                s["id"],
                completed=1,
                matched_activity_id=str(best_match.get("garmin_activity_id", "")),
                actual_distance_km=round(act_dist, 1),
                actual_duration_min=round(act_dur, 0),
            )


def _find_best_activity(session, acts_by_date, scheduled_date):
    """Trouve la meilleure activité correspondant à une séance."""
    stype = session["session_type"]
    is_running = stype in RUNNING_TYPES
    is_strength = stype == "strength"

    # Chercher sur la date exacte puis ±1 jour
    try:
        sched_dt = datetime.strptime(scheduled_date, "%Y-%m-%d")
    except ValueError:
        return None

    dates_to_check = [
        scheduled_date,
        (sched_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
        (sched_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    candidates = []
    for d in dates_to_check:
        for act in acts_by_date.get(d, []):
            act_type = act.get("activity_type", "")
            if is_running and "running" in act_type.lower():
                candidates.append(act)
            elif is_strength and "strength" in act_type.lower():
                candidates.append(act)
            elif not is_running and not is_strength and act_type:
                candidates.append(act)

    if not candidates:
        # Fallback : prendre toute activité running sur la date exacte
        if is_running:
            for act in acts_by_date.get(scheduled_date, []):
                candidates.append(act)

    if not candidates:
        return None

    # Choisir la plus proche en distance si plusieurs
    planned_km = session.get("distance_km") or 0
    if len(candidates) == 1:
        return candidates[0]

    return min(candidates, key=lambda a: abs((a.get("distance_m") or 0) / 1000 - planned_km))


def _detect_missed_sessions(plan_id, sessions, today_str):
    """Marque les séances passées sans activité comme manquées."""
    for s in sessions:
        if s.get("completed") or s.get("missed") or s.get("matched_activity_id"):
            continue
        if s["session_type"] in ("rest", "strength"):
            continue
        sched = s.get("scheduled_date")
        if not sched or sched >= today_str:
            continue
        update_session(s["id"], missed=1)
        save_adaptation_log(
            plan_id, "missed_session",
            f"Séance manquée : {s.get('title', s['session_type'])} du {sched}",
            {"session_id": s["id"], "scheduled_date": sched, "type": s["session_type"]},
        )


def _adjust_next_week_volume(plan_id, current_week, sessions, activities, profile):
    """Ajuste le volume de la semaine suivante basé sur le volume réel."""
    next_week = current_week + 1

    # Séances de la semaine courante et suivante
    current_sessions = [s for s in sessions if s["week_number"] == current_week]
    next_sessions = [s for s in sessions if s["week_number"] == next_week]

    if not next_sessions:
        return

    # Volume réel de la semaine courante
    actual_km = _compute_actual_weekly_km(current_sessions, activities)
    planned_km = sum(s.get("distance_km") or 0 for s in current_sessions)

    # Volume réel de la semaine précédente (pour le cap +10%)
    if current_week > 1:
        prev_sessions = [s for s in sessions if s["week_number"] == current_week - 1]
        prev_actual_km = _compute_actual_weekly_km(prev_sessions, activities)
    else:
        prev_actual_km = actual_km

    # Si la semaine courante n'est pas terminée, ne pas ajuster
    today = datetime.now()
    last_day_current = max(
        (s.get("scheduled_date") or "") for s in current_sessions
    )
    if last_day_current and last_day_current >= today.strftime("%Y-%m-%d"):
        return  # semaine pas finie

    # Calculer le nouveau volume cible
    planned_next_km = sum(s.get("distance_km") or 0 for s in next_sessions)

    if actual_km <= 0:
        # Aucune activité cette semaine — réduire significativement
        target_km = max(planned_next_km * 0.6, 10)
    elif actual_km < planned_km * 0.8:
        # Déficit important — cap à +5% du réel
        target_km = actual_km * 1.05
    elif actual_km > planned_km * 1.10:
        # Surplus — maintenir stable
        target_km = actual_km
    else:
        # Normal — progression basée sur le réel
        target_km = actual_km * (1 + ATHLETE_PROFILE["max_volume_increase_pct"] / 100)

    # Cap absolu +3km vs semaine précédente réelle
    target_km = min(target_km, prev_actual_km + 3) if prev_actual_km > 0 else target_km
    # Cap +10% vs semaine précédente réelle
    target_km = min(target_km, prev_actual_km * 1.10) if prev_actual_km > 0 else target_km

    # Semaine récup (toutes les 3 semaines)
    is_recovery = (next_week % ATHLETE_PROFILE["recovery_week_interval"] == 0)
    if is_recovery:
        target_km *= (1 - ATHLETE_PROFILE["recovery_week_reduction_pct"] / 100)

    target_km = round(target_km, 1)

    # Si le changement est < 1km, ne pas ajuster (éviter le bruit)
    if abs(target_km - planned_next_km) < 1.0:
        return

    # Recalculer les allures
    vdot = profile.get("vdot") or 45
    all_acts = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_acts)
    if paces is None:
        paces = calculate_training_paces(vdot)

    # Redistribuer le volume (25/30/45)
    day1_km = round(target_km * 0.25, 1)
    day2_km = round(target_km * 0.30, 1)
    day3_km = round(target_km * 0.45, 1)

    for s in next_sessions:
        if s["session_type"] in ("rest", "strength"):
            continue

        old_km = s.get("distance_km") or 0
        dow = s["day_of_week"]

        # Déterminer la nouvelle distance selon le jour
        if dow == 1:  # Mardi
            new_km = day1_km
        elif dow == 3:  # Jeudi
            new_km = day2_km
        elif dow == 5:  # Samedi
            new_km = day3_km
        else:
            continue

        if abs(new_km - old_km) < 0.5:
            continue

        # Regénérer la séance avec la bonne distance
        phase = s.get("phase", "base")
        new_session = _regenerate_session(s["session_type"], new_km, phase, paces)

        update_session(
            s["id"],
            distance_km=new_session["distance_km"],
            duration_min=new_session.get("duration_min"),
            title=new_session["title"],
            description=new_session["description"],
            target_pace=new_session.get("target_pace"),
            original_distance_km=old_km if not s.get("original_distance_km") else s["original_distance_km"],
            adjusted=1,
            adjustment_reason=f"Volume adapté : {old_km}→{new_session['distance_km']} km (réel S{current_week}: {actual_km} km)",
            adapted_at=datetime.now().isoformat(),
        )

    save_adaptation_log(
        plan_id, "volume_adjust",
        f"Volume S{next_week} ajusté : {planned_next_km}→{target_km} km (réel S{current_week}: {actual_km} km)",
        {"current_week": current_week, "actual_km": actual_km,
         "planned_km": planned_km, "new_target": target_km},
    )


def _regenerate_session(session_type, distance_km, phase, paces):
    """Regénère les détails d'une séance avec une nouvelle distance."""
    if session_type == "easy":
        return _easy_run(distance_km, paces)
    elif session_type == "long_run":
        return _long_run(distance_km, paces)
    elif session_type == "intervals":
        # Adapter les reps selon la distance
        reps = max(4, min(10, round(distance_km / 0.8)))
        return _interval_session(distance_km, reps, 1, 1.5, paces)
    elif session_type == "tempo":
        tempo_km = round(distance_km * 0.4, 1)
        return _tempo_session(distance_km, tempo_km, paces)
    else:
        return _easy_run(distance_km, paces)


def _compute_actual_weekly_km(week_sessions, activities):
    """Calcule les km réellement courus durant une semaine."""
    total = 0
    # Km des séances matchées
    for s in week_sessions:
        if s.get("actual_distance_km"):
            total += s["actual_distance_km"]
            continue
        if s.get("matched_activity_id"):
            # Chercher la distance dans les activités
            for act in activities:
                if str(act.get("garmin_activity_id")) == str(s["matched_activity_id"]):
                    total += (act.get("distance_m") or 0) / 1000
                    break

    # Ajouter les activités extra (sur les dates de la semaine, non matchées)
    matched_ids = {
        str(s.get("matched_activity_id"))
        for s in week_sessions
        if s.get("matched_activity_id")
    }
    week_dates = {s.get("scheduled_date") for s in week_sessions if s.get("scheduled_date")}
    if week_dates:
        min_date = min(week_dates)
        max_date = max(week_dates)
        for act in activities:
            act_id = str(act.get("garmin_activity_id", ""))
            act_date = (act.get("activity_date") or "")[:10]
            act_type = (act.get("activity_type") or "").lower()
            if (act_id not in matched_ids
                    and act_date >= min_date and act_date <= max_date
                    and "running" in act_type):
                total += (act.get("distance_m") or 0) / 1000

    return round(total, 1)


def _check_vdot_recalibration(plan_id, plan, sessions, profile, today_str):
    """Recalibre les allures si le VDOT a changé de >= 1 point."""
    current_vdot = profile.get("vdot")
    ref_vdot = plan.get("reference_vdot")

    if not current_vdot or not ref_vdot:
        return
    if abs(current_vdot - ref_vdot) < 1.0:
        return

    # Recalculer les allures
    all_acts = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_acts)
    if paces is None:
        paces = calculate_training_paces(current_vdot)

    # Mettre à jour toutes les séances futures
    updated = 0
    for s in sessions:
        sched = s.get("scheduled_date")
        if not sched or sched < today_str:
            continue
        if s["session_type"] in ("rest", "strength"):
            continue

        new_session = _regenerate_session(
            s.get("original_session_type") or s["session_type"],
            s.get("distance_km") or 5,
            s.get("phase", "base"),
            paces,
        )
        update_session(
            s["id"],
            target_pace=new_session.get("target_pace"),
            description=new_session["description"],
            adjusted=1,
            adjustment_reason=f"Allures recalibrées (VDOT {ref_vdot}→{current_vdot})",
            adapted_at=datetime.now().isoformat(),
        )
        updated += 1

    # Mettre à jour le VDOT de référence
    conn = get_db()
    conn.execute(
        "UPDATE training_plan SET reference_vdot = ? WHERE id = ?",
        (current_vdot, plan_id)
    )
    conn.commit()
    conn.close()

    save_adaptation_log(
        plan_id, "vdot_recalibrate",
        f"VDOT {ref_vdot}→{current_vdot} : {updated} séances recalibrées",
        {"old_vdot": ref_vdot, "new_vdot": current_vdot, "sessions_updated": updated},
    )


def _apply_recovery_adjustments(plan_id, sessions, today_str, today_recovery, profile):
    """Applique et persiste les ajustements récupération pour aujourd'hui et demain."""
    recovery_score = today_recovery.get("recovery_score")
    hrv_7day = today_recovery.get("hrv_7day_avg")
    if recovery_score is None:
        return

    vdot = profile.get("vdot") or 45
    all_acts = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_acts)
    if paces is None:
        paces = calculate_training_paces(vdot)

    tomorrow_str = (datetime.strptime(today_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    for s in sessions:
        sched = s.get("scheduled_date")
        if not sched or sched not in (today_str, tomorrow_str):
            continue
        if s["session_type"] in ("rest", "strength"):
            continue
        if s.get("completed") or s.get("missed"):
            continue
        # Ne pas ré-ajuster si déjà ajusté par la récupération aujourd'hui
        if s.get("adapted_at"):
            adapted_date = s["adapted_at"][:10]
            if adapted_date == today_str and s.get("adjusted"):
                continue

        adjusted = adjust_session_for_recovery(s, recovery_score, hrv_7day, paces)
        if adjusted.get("adjusted"):
            # Sauvegarder le type original avant modification
            orig_type = s.get("original_session_type") or s["session_type"]
            orig_km = s.get("original_distance_km") or s.get("distance_km")

            update_session(
                s["id"],
                session_type=adjusted["session_type"],
                title=adjusted["title"],
                description=adjusted["description"],
                distance_km=adjusted.get("distance_km"),
                duration_min=adjusted.get("duration_min"),
                target_pace=adjusted.get("target_pace"),
                target_hr_zone=adjusted.get("target_hr_zone"),
                original_session_type=orig_type,
                original_distance_km=orig_km,
                adjusted=1,
                adjustment_reason=adjusted.get("adjustment_reason", "Ajustement récupération"),
                adapted_at=datetime.now().isoformat(),
            )
            save_adaptation_log(
                plan_id, "recovery_adjust",
                f"{adjusted.get('adjustment_reason', '')} — {sched}",
                {"session_id": s["id"], "recovery_score": recovery_score,
                 "original_type": orig_type, "new_type": adjusted["session_type"]},
            )


def handle_bike_replacement(bike_activity, pain_level=3, target_date=None):
    """Remplace la séance du jour par du vélo et adapte les séances futures.

    Quand l'utilisateur fait du vélo à la place de la course (douleur tibiale),
    on marque la séance comme complétée par vélo et on adapte les prochaines
    séances pour réduire l'impact (plus de Z2, moins d'intensité, proposer
    du vélo comme alternative).

    Args:
        bike_activity: dict Garmin de l'activité vélo
        pain_level: 1-5 (1=léger, 5=très douloureux)
        target_date: date de la séance à remplacer (défaut: aujourd'hui ou hier)
    Returns:
        dict avec les infos du remplacement ou None si pas de séance à remplacer
    """
    plan, sessions = get_active_plan()
    if not plan or not sessions:
        return None

    plan_id = plan["id"]
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    if target_date:
        target_str = target_date if isinstance(target_date, str) else target_date.strftime("%Y-%m-%d")
    else:
        target_str = None

    # Trouver la séance running à remplacer (aujourd'hui ou hier)
    target_session = None
    for s in sessions:
        sched = s.get("scheduled_date")
        if not sched:
            continue
        if s["session_type"] in ("rest", "strength"):
            continue
        if s.get("completed") or s.get("missed"):
            continue
        if target_str:
            if sched == target_str:
                target_session = s
                break
        elif sched in (today_str, yesterday_str):
            target_session = s
            break

    if not target_session:
        return None

    # Calculer l'équivalent course du vélo réalisé
    bike_km = (bike_activity.get("distance") or bike_activity.get("distance_m") or 0) / 1000
    bike_dur = (bike_activity.get("duration") or bike_activity.get("duration_s") or 0) / 60
    run_equiv_km = round(bike_km / BIKE_RATIO_DISTANCE, 1)
    run_equiv_min = round(bike_dur / BIKE_RATIO_TIME, 0)

    orig_type = target_session.get("original_session_type") or target_session["session_type"]
    orig_km = target_session.get("original_distance_km") or target_session.get("distance_km")

    # Marquer la séance comme complétée par vélo
    update_session(
        target_session["id"],
        completed=1,
        matched_activity_id=str(bike_activity.get("activityId", "")),
        actual_distance_km=run_equiv_km,
        actual_duration_min=run_equiv_min,
        original_session_type=orig_type,
        original_distance_km=orig_km,
        adjusted=1,
        adjustment_reason=f"Remplacé par vélo ({bike_km:.1f} km, {bike_dur:.0f} min) — douleur tibiale {pain_level}/5",
        adapted_at=datetime.now().isoformat(),
    )

    save_adaptation_log(
        plan_id, "bike_replace",
        f"Séance {orig_type} remplacée par vélo ({bike_km:.1f} km) — douleur {pain_level}/5",
        {"session_id": target_session["id"], "bike_km": bike_km,
         "run_equiv_km": run_equiv_km, "pain_level": pain_level,
         "original_type": orig_type},
    )

    # Adapter les séances futures selon le niveau de douleur
    _adapt_for_shin_pain(plan_id, sessions, today_str, pain_level)

    result = {
        "session_replaced": target_session["title"],
        "bike_km": round(bike_km, 1),
        "bike_dur_min": round(bike_dur, 0),
        "run_equiv_km": run_equiv_km,
        "pain_level": pain_level,
        "adaptations_applied": True,
    }

    return result


def _adapt_for_shin_pain(plan_id, sessions, today_str, pain_level):
    """Adapte les séances futures quand l'utilisateur a mal aux tibias.

    Logique :
    - Douleur 1-2 : pas de changement majeur, juste un avertissement
    - Douleur 3 : convertir la prochaine séance intense en Z2 + proposer vélo
    - Douleur 4 : convertir les 2-3 prochaines séances en Z2 ou repos
    - Douleur 5 : convertir toute la semaine restante en repos/vélo
    """
    if pain_level <= 2:
        # Juste un warning sur la prochaine séance
        for s in sessions:
            sched = s.get("scheduled_date")
            if not sched or sched <= today_str:
                continue
            if s["session_type"] in ("rest", "strength"):
                continue
            if s.get("completed") or s.get("missed"):
                continue
            update_session(
                s["id"],
                adjusted=1,
                adjustment_reason=f"Vigilance tibias (douleur {pain_level}/5) — rester en Z2, marcher si douleur",
                adapted_at=datetime.now().isoformat(),
            )
            break  # Juste la prochaine
        return

    profile = get_profile()
    vdot = profile.get("vdot") or 45
    all_acts = get_cached_activities(limit=100)
    paces = get_calibrated_paces(all_acts)
    if paces is None:
        paces = calculate_training_paces(vdot)

    # Nombre de séances à adapter selon la douleur
    if pain_level == 3:
        max_adapt = 2   # Prochaines 2 séances running
    elif pain_level == 4:
        max_adapt = 4   # Prochaines 4 séances running
    else:  # 5
        max_adapt = 99  # Toute la semaine

    adapted_count = 0
    for s in sessions:
        if adapted_count >= max_adapt:
            break
        sched = s.get("scheduled_date")
        if not sched or sched <= today_str:
            continue
        if s["session_type"] in ("rest", "strength"):
            continue
        if s.get("completed") or s.get("missed"):
            continue

        orig_type = s.get("original_session_type") or s["session_type"]
        orig_km = s.get("original_distance_km") or s.get("distance_km") or 5

        if pain_level >= 5:
            # Repos complet ou vélo uniquement
            bike_km = round(orig_km * BIKE_RATIO_DISTANCE, 1)
            bike_min = round(orig_km * 7 * BIKE_RATIO_TIME, 0)  # ~7 min/km * ratio
            update_session(
                s["id"],
                session_type="easy",
                title=f"Vélo Z2 — {bike_km} km (remplace course)",
                description=(
                    f"REPOS TIBIAS : Vélo {bike_km} km ou ~{bike_min:.0f} min en Z2 "
                    f"(FC < {ATHLETE_PROFILE['fc_footing_max']} bpm). "
                    "Pas de course tant que la douleur ne diminue pas. "
                    "Glaçage 15 min après la séance."
                ),
                distance_km=0,
                target_pace=None,
                target_hr_zone="Z2",
                original_session_type=orig_type,
                original_distance_km=orig_km,
                adjusted=1,
                adjustment_reason=f"Vélo imposé — douleur tibiale {pain_level}/5",
                adapted_at=datetime.now().isoformat(),
            )
        elif pain_level >= 4:
            # Footing très léger ou vélo
            reduced_km = round(orig_km * 0.5, 1)
            bike_km = round(orig_km * BIKE_RATIO_DISTANCE, 1)
            new_session = _easy_run(reduced_km, paces)
            update_session(
                s["id"],
                session_type="easy",
                title=new_session["title"],
                description=(
                    f"{new_session['description']} OU Alternative vélo : {bike_km} km en Z2. "
                    "STOPPER immédiatement si douleur tibiale > 3/5."
                ),
                distance_km=reduced_km,
                duration_min=new_session.get("duration_min"),
                target_pace=new_session.get("target_pace"),
                target_hr_zone="Z2",
                original_session_type=orig_type,
                original_distance_km=orig_km,
                adjusted=1,
                adjustment_reason=f"Allégé + option vélo — douleur tibiale {pain_level}/5",
                adapted_at=datetime.now().isoformat(),
            )
        else:  # pain_level == 3
            if s["session_type"] in ("intervals", "tempo"):
                # Convertir la qualité en Z2
                new_session = _easy_run(orig_km, paces)
                bike_km = round(orig_km * BIKE_RATIO_DISTANCE, 1)
                update_session(
                    s["id"],
                    session_type="easy",
                    title=new_session["title"],
                    description=(
                        f"{new_session['description']} OU vélo {bike_km} km en Z2. "
                        "Douleur tibiale signalée : pas d'intensité. "
                        "Marcher dans les côtes si douleur."
                    ),
                    distance_km=orig_km,
                    duration_min=new_session.get("duration_min"),
                    target_pace=new_session.get("target_pace"),
                    target_hr_zone="Z2",
                    original_session_type=orig_type,
                    original_distance_km=orig_km,
                    adjusted=1,
                    adjustment_reason=f"Intensité → Z2 + option vélo — douleur tibiale {pain_level}/5",
                    adapted_at=datetime.now().isoformat(),
                )
            else:
                # Footing → garder mais avertir + proposer vélo
                bike_km = round(orig_km * BIKE_RATIO_DISTANCE, 1)
                update_session(
                    s["id"],
                    adjusted=1,
                    adjustment_reason=f"Option vélo {bike_km} km si douleur tibiale persiste ({pain_level}/5)",
                    adapted_at=datetime.now().isoformat(),
                )

        adapted_count += 1

    if adapted_count > 0:
        save_adaptation_log(
            plan_id, "shin_pain_adapt",
            f"Douleur tibiale {pain_level}/5 : {adapted_count} séances adaptées (Z2/vélo)",
            {"pain_level": pain_level, "sessions_adapted": adapted_count},
        )
