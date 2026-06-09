import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
# Stockage en local (pas sur Synology Drive) pour éviter les verrous de synchro
DATA_DIR = os.path.join(os.path.expanduser("~"), ".appcoach")
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, "appcoach.db")
GARMIN_TOKEN_DIR = os.path.join(DATA_DIR, "garmin_tokens")

# Profil athlète (depuis dossier_sportif.docx)
ATHLETE_PROFILE = {
    "age": 23,
    "height_cm": 186,
    "weight_kg": 72,
    "fc_max": 196,            # observée en course (194-196); 198 était une hypothèse
    "fc_repos_baseline": 53,
    "lthr_run": 178,          # FC seuil course (efforts soutenus 175-181)
    "lthr_bike": 173,         # FC seuil vélo (efforts soutenus 169-176)
    "hrv_baseline": 51,
    "hrv_alert_threshold": 49,
    "fc_footing_max": 155,  # Plafond strict Z2 (contrainte périostites)
    "max_volume_increase_pct": 10,  # Max +10%/semaine
    "recovery_week_interval": 3,  # Semaine de récup toutes les 3 semaines
    "recovery_week_reduction_pct": 25,
    # VO2max/VDOT validés par analyse des splits d'intervalles (mai 2026)
    # Source: 1000m @ 4:09/km FC 182 (15 mai), HR-method p75=47
    "validated_vo2max": 47,
    "validated_vdot": 47,
    "validated_vma": 13.4,
    "vo2max_source": "Intervals analysis: 1000m @ 4:09/km FC 182 (15 mai), HR-method p75=47",
}

# Zones FC CALIBRÉES sur efforts durs réels (juin 2026)
# LTHR (FC seuil) déduite des efforts soutenus >=30min:
#   Course ~178 bpm | Vélo ~173 bpm | FC max observée ~196 (199 = artefact marche)
# Zones vélo = % de LTHR vélo (173). Méthode Friel/Coggan.
HR_ZONES = {
    "Z1": {"name": "Récupération", "min": 0,   "max": 140},  # <81% LTHR
    "Z2": {"name": "Endurance",    "min": 140, "max": 155},  # 81-90% — le "facile"
    "Z3": {"name": "Tempo",        "min": 155, "max": 162},  # 90-94%
    "Z4": {"name": "Seuil",        "min": 162, "max": 173},  # 94-100%
    "Z5": {"name": "VO2max",       "min": 173, "max": 220},  # >100% LTHR
}
