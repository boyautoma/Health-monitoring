from datetime import datetime, timedelta
from config import ATHLETE_PROFILE


def calculate_recovery_score(hrv_7day_avg, sleep_score, sleep_duration_min,
                              rhr, stress_avg, training_readiness=None):
    """
    Calcule un score de récupération composite (0-100).
    Pondération: HRV 40%, Sommeil 30%, FC repos 15%, Stress 15%
    """
    score = 0

    # --- HRV (40% du score) ---
    hrv_baseline = ATHLETE_PROFILE["hrv_baseline"]
    if hrv_7day_avg is not None:
        # Score proportionnel: baseline = 100%, <alert = 0%
        hrv_min = ATHLETE_PROFILE["hrv_alert_threshold"] - 5  # 44
        hrv_max = hrv_baseline + 10  # 61
        hrv_pct = max(0, min(100, (hrv_7day_avg - hrv_min) / (hrv_max - hrv_min) * 100))
        score += hrv_pct * 0.40
    else:
        score += 50 * 0.40  # Valeur neutre si pas de données

    # --- Sommeil (30% du score) ---
    sleep_sub = 0
    if sleep_score is not None:
        sleep_sub += sleep_score * 0.6  # Score Garmin sur 100
    else:
        sleep_sub += 50 * 0.6

    if sleep_duration_min is not None:
        # Optimal: 7h-8h30 (420-510 min)
        if sleep_duration_min >= 420:
            duration_pct = min(100, sleep_duration_min / 510 * 100)
        else:
            duration_pct = max(0, sleep_duration_min / 420 * 100)
        sleep_sub += duration_pct * 0.4
    else:
        sleep_sub += 50 * 0.4

    score += sleep_sub * 0.30

    # --- FC repos (15% du score) ---
    fc_repos_baseline = ATHLETE_PROFILE["fc_repos_baseline"]
    if rhr is not None:
        # Plus la FC repos est basse vs baseline, meilleur le score
        diff = rhr - fc_repos_baseline
        if diff <= 0:
            rhr_pct = 100
        elif diff <= 5:
            rhr_pct = 100 - (diff * 15)  # -15 pts par bpm au-dessus
        else:
            rhr_pct = max(0, 25 - (diff - 5) * 10)
        score += rhr_pct * 0.15
    else:
        score += 50 * 0.15

    # --- Stress (15% du score) ---
    if stress_avg is not None:
        # Garmin stress: 0-100 (bas = bon)
        stress_pct = max(0, 100 - stress_avg)
        score += stress_pct * 0.15
    else:
        score += 50 * 0.15

    return round(min(100, max(0, score)))


def get_recovery_level(score):
    """Retourne le niveau de récupération et la couleur associée."""
    if score >= 75:
        return "excellent", "success", "Récupération excellente"
    elif score >= 50:
        return "moderate", "warning", "Récupération modérée"
    elif score >= 30:
        return "low", "danger", "Récupération insuffisante"
    else:
        return "critical", "danger", "Récupération critique"


def get_training_adjustment(score, hrv_7day_avg):
    """Détermine l'ajustement du plan selon le score de récupération."""
    alerts = []
    adjustment = "normal"

    # Alerte HRV critique
    if hrv_7day_avg is not None and hrv_7day_avg < ATHLETE_PROFILE["hrv_alert_threshold"]:
        alerts.append({
            "level": "danger",
            "title": "HRV en dessous du seuil d'alerte",
            "message": f"HRV moy. 7j : {hrv_7day_avg:.0f} ms (seuil : {ATHLETE_PROFILE['hrv_alert_threshold']} ms). "
                       "Réduire la charge d'entraînement.",
        })
        adjustment = "reduce_intensity"

    # Ajustement basé sur le score global
    if score >= 75:
        adjustment = "normal"
    elif score >= 50:
        adjustment = "reduce_intensity"
        alerts.append({
            "level": "warning",
            "title": "Récupération modérée",
            "message": "Remplacer la séance intensive par un footing Z2 ou réduire le volume.",
        })
    elif score >= 30:
        adjustment = "easy_only"
        alerts.append({
            "level": "danger",
            "title": "Récupération insuffisante",
            "message": "Séance très légère uniquement (footing court Z1-Z2 ou repos actif).",
        })
    else:
        adjustment = "rest"
        alerts.append({
            "level": "danger",
            "title": "Repos recommandé",
            "message": "Récupération critique. Repos complet aujourd'hui.",
        })

    return adjustment, alerts


def generate_recovery_advice(sleep_data, hrv_data, rhr, stress_data):
    """Génère des conseils personnalisés de récupération."""
    advice = []

    # --- Conseils sommeil ---
    if sleep_data:
        if sleep_data.get("score") and sleep_data["score"] < 70:
            advice.append({
                "category": "sommeil",
                "icon": "moon",
                "title": "Qualité de sommeil insuffisante",
                "message": f"Score sommeil : {sleep_data['score']}/100. "
                           "Essaie de limiter les écrans 1h avant le coucher et de garder une chambre fraîche (18-19°C).",
            })

        duration_min = sleep_data.get("duration_min", 0)
        if duration_min and duration_min < 390:  # < 6h30
            advice.append({
                "category": "sommeil",
                "icon": "clock",
                "title": "Durée de sommeil insuffisante",
                "message": f"Tu as dormi {duration_min // 60}h{duration_min % 60:02d}. "
                           "Vise 7h30-8h pour une récupération optimale.",
            })

        bedtime = sleep_data.get("bedtime")
        if bedtime:
            try:
                if isinstance(bedtime, (int, float)):
                    bed_hour = datetime.fromtimestamp(bedtime / 1000).hour
                else:
                    bed_hour = int(str(bedtime)[11:13]) if len(str(bedtime)) > 13 else None
                if bed_hour is not None and (bed_hour >= 1 and bed_hour < 6):
                    advice.append({
                        "category": "sommeil",
                        "icon": "alert-triangle",
                        "title": "Coucher trop tardif",
                        "message": "Tu te couches régulièrement après 1h du matin. "
                                   "Essaie d'avancer ton coucher de 30 min chaque semaine. "
                                   "Le sommeil avant minuit est le plus réparateur.",
                    })
            except (ValueError, TypeError):
                pass

    # --- Conseils HRV ---
    if hrv_data:
        weekly_avg = hrv_data.get("weekly_avg")
        if weekly_avg and weekly_avg < ATHLETE_PROFILE["hrv_alert_threshold"]:
            advice.append({
                "category": "hrv",
                "icon": "activity",
                "title": "HRV basse — stress ou fatigue accumulée",
                "message": f"HRV moy. 7j : {weekly_avg:.0f} ms (baseline : {ATHLETE_PROFILE['hrv_baseline']} ms). "
                           "Privilégie les séances faciles cette semaine. "
                           "Techniques recommandées : respiration 4-7-8, marche en nature, sieste 20 min.",
            })

    # --- Conseils FC repos ---
    if rhr is not None:
        diff = rhr - ATHLETE_PROFILE["fc_repos_baseline"]
        if diff >= 5:
            advice.append({
                "category": "coeur",
                "icon": "heart",
                "title": "FC repos élevée",
                "message": f"FC repos : {rhr} bpm (baseline : {ATHLETE_PROFILE['fc_repos_baseline']} bpm, "
                           f"+{diff} bpm). Signe possible de fatigue, déshydratation ou début de maladie. "
                           "Hydrate-toi bien et envisage un repos supplémentaire.",
            })

    # --- Conseils spécifiques périostites ---
    advice.append({
        "category": "periostites",
        "icon": "shield",
        "title": "Protocole post-course (tibias)",
        "message": "Après chaque course : 10-15 min de glaçage sur les tibias. "
                   "Auto-massage avec rouleau ou balle le long du tibia (3-5 min par jambe). "
                   "Étirements doux des mollets et du tibial antérieur.",
    })

    # --- Conseil nutrition récupération ---
    advice.append({
        "category": "nutrition",
        "icon": "coffee",
        "title": "Fenêtre de récupération",
        "message": "Dans les 30 min après l'effort : collation avec protéines + glucides "
                   "(ex: banane + yaourt grec, ou lait chocolaté). "
                   "Anti-inflammatoires naturels : curcuma, gingembre, cerises.",
    })

    return advice


def check_strength_alert(last_strength_date):
    """Vérifie si le renforcement musculaire est manqué depuis trop longtemps."""
    if last_strength_date is None:
        return {
            "level": "danger",
            "title": "Renforcement musculaire manquant",
            "message": "Aucune séance de renforcement enregistrée. "
                       "Le renforcement est ESSENTIEL pour prévenir les périostites. "
                       "Reprends dès aujourd'hui (mercredi ou vendredi).",
        }

    try:
        if isinstance(last_strength_date, str):
            last_date = datetime.strptime(last_strength_date[:10], "%Y-%m-%d")
        else:
            last_date = last_strength_date
        days_since = (datetime.now() - last_date).days

        if days_since > 14:
            return {
                "level": "danger",
                "title": f"Renforcement manqué depuis {days_since} jours",
                "message": "Plus de 2 semaines sans renforcement musculaire. "
                           "Risque accru de rechute des périostites. Reprends IMMÉDIATEMENT.",
            }
        elif days_since > 7:
            return {
                "level": "warning",
                "title": f"Renforcement manqué depuis {days_since} jours",
                "message": "Plus d'une semaine sans renforcement. Planifie une séance dans les 2 prochains jours.",
            }
    except (ValueError, TypeError):
        pass

    return None
