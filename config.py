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
    "fc_max": 198,
    "fc_repos_baseline": 53,
    "hrv_baseline": 51,
    "hrv_alert_threshold": 49,
    "fc_footing_max": 155,  # Plafond strict Z2 (contrainte périostites)
    "max_volume_increase_pct": 10,  # Max +10%/semaine
    "recovery_week_interval": 3,  # Semaine de récup toutes les 3 semaines
    "recovery_week_reduction_pct": 25,
}

# Zones FC (Karvonen) - FC max 198, FC repos 53
HR_ZONES = {
    "Z1": {"name": "Récupération", "min": 0, "max": 140},
    "Z2": {"name": "Aérobie base", "min": 140, "max": 155},
    "Z3": {"name": "Tempo", "min": 155, "max": 169},
    "Z4": {"name": "Seuil", "min": 169, "max": 184},
    "Z5": {"name": "Maximum", "min": 184, "max": 220},
}
