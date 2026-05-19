import os
import time
import logging
from datetime import datetime, timedelta
from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from config import GARMIN_TOKEN_DIR

logger = logging.getLogger(__name__)


class GarminClient:
    def __init__(self):
        self.client = None
        self._ensure_token_dir()

    def _ensure_token_dir(self):
        os.makedirs(GARMIN_TOKEN_DIR, exist_ok=True)

    def login(self, email, password):
        try:
            self.client = Garmin(email, password)
            self.client.login()
            self.client.garth.dump(GARMIN_TOKEN_DIR)
            return True
        except GarminConnectAuthenticationError:
            logger.error("Échec d'authentification Garmin")
            return False
        except GarminConnectTooManyRequestsError:
            logger.error("Trop de requêtes Garmin - attendre avant de réessayer")
            return False
        except Exception as e:
            logger.error(f"Erreur connexion Garmin: {e}")
            return False

    def resume_session(self):
        try:
            self.client = Garmin()
            self.client.garth.load(GARMIN_TOKEN_DIR)
            self.client.login()
            self.client.garth.dump(GARMIN_TOKEN_DIR)
            return True
        except Exception:
            return False

    def is_connected(self):
        return self.client is not None

    def _safe_call(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GarminConnectTooManyRequestsError:
            logger.warning("Rate limited - attente 60s")
            time.sleep(60)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Échec après retry: {e}")
                return None
        except Exception as e:
            logger.error(f"Erreur API Garmin: {e}")
            return None

    # --- Activités ---
    def get_running_activities(self, start_date, end_date):
        data = self._safe_call(
            self.client.get_activities_by_date,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            "running",
        )
        return data or []

    def get_recent_activities(self, weeks=8):
        end = datetime.now()
        start = end - timedelta(weeks=weeks)
        return self.get_running_activities(start, end)

    def get_cycling_activities(self, start_date, end_date):
        """Récupère les activités vélo sur une période."""
        data = self._safe_call(
            self.client.get_activities_by_date,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            "cycling",
        )
        return data or []

    def get_today_cycling(self):
        """Récupère l'activité vélo du jour (la plus récente)."""
        today = datetime.now()
        start = today.replace(hour=0, minute=0, second=0)
        acts = self.get_cycling_activities(start, today)
        if not acts:
            # Chercher aussi hier (si le user dit "hier j'ai fait du vélo")
            yesterday = today - timedelta(days=1)
            acts = self.get_cycling_activities(yesterday, today)
        return acts[0] if acts else None

    def get_activity_details(self, activity_id):
        return self._safe_call(self.client.get_activity, activity_id)

    def get_activity_splits(self, activity_id):
        return self._safe_call(self.client.get_activity_splits, activity_id)

    def get_activity_hr_zones(self, activity_id):
        return self._safe_call(self.client.get_activity_hr_in_timezones, activity_id)

    # --- Métriques de performance ---
    def get_vo2max(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_max_metrics, date_str)
        if data and isinstance(data, list) and len(data) > 0:
            for metric in data:
                if metric.get("generic", {}).get("vo2MaxPreciseValue"):
                    return metric["generic"]["vo2MaxPreciseValue"]
                if metric.get("generic", {}).get("vo2MaxValue"):
                    return metric["generic"]["vo2MaxValue"]
        return None

    def get_training_status(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        return self._safe_call(self.client.get_training_status, date_str)

    def get_training_readiness(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_training_readiness, date_str)
        if data and isinstance(data, dict):
            return data.get("score") or data.get("trainingReadinessScore")
        return None

    def get_race_predictions(self):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        return self._safe_call(self.client.get_race_predictions, start, end)

    # --- Récupération et santé ---
    def get_sleep_data(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_sleep_data, date_str)
        if not data:
            return None
        daily = data.get("dailySleepDTO", {})
        return {
            "score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
            "duration_seconds": daily.get("sleepTimeSeconds"),
            "duration_min": (daily.get("sleepTimeSeconds") or 0) // 60,
            "bedtime": daily.get("sleepStartTimestampLocal"),
            "wake_time": daily.get("sleepEndTimestampLocal"),
            "deep_sleep_min": (daily.get("deepSleepSeconds") or 0) // 60,
            "light_sleep_min": (daily.get("lightSleepSeconds") or 0) // 60,
            "rem_sleep_min": (daily.get("remSleepSeconds") or 0) // 60,
            "awake_min": (daily.get("awakeSleepSeconds") or 0) // 60,
        }

    def get_hrv_data(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_hrv_data, date_str)
        if not data:
            return None
        summary = data.get("hrvSummary", {})
        return {
            "weekly_avg": summary.get("weeklyAvg"),
            "last_night": summary.get("lastNight"),
            "status": summary.get("status"),
            "baseline_low": summary.get("baselineLowUpper"),
            "baseline_balanced": summary.get("baselineBalancedLow"),
        }

    def get_stress_data(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_all_day_stress, date_str)
        if not data:
            return None
        return {
            "avg_stress": data.get("overallStressLevel"),
            "rest_stress": data.get("restStressLevel"),
            "high_stress_pct": data.get("highStressDuration", 0),
        }

    def get_resting_hr(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        data = self._safe_call(self.client.get_rhr_day, date_str)
        if data and isinstance(data, dict):
            for entry in data.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_RESTING_HEART_RATE", []):
                if entry.get("value"):
                    return int(entry["value"])
        return None

    def get_heart_rates(self, date=None):
        date_str = (date or datetime.now()).strftime("%Y-%m-%d")
        return self._safe_call(self.client.get_heart_rates, date_str)

    def get_body_battery(self, days=7):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self._safe_call(self.client.get_body_battery, start, end)

    # --- Données agrégées pour le dashboard ---
    def get_daily_summary(self, date=None):
        """Récupère un résumé complet d'une journée pour le dashboard."""
        target_date = date or datetime.now()
        return {
            "vo2max": self.get_vo2max(target_date),
            "training_readiness": self.get_training_readiness(target_date),
            "sleep": self.get_sleep_data(target_date),
            "hrv": self.get_hrv_data(target_date),
            "stress": self.get_stress_data(target_date),
            "rhr": self.get_resting_hr(target_date),
        }

    def get_weekly_volumes(self, weeks=8):
        """Calcule le volume hebdomadaire (km) sur les N dernières semaines."""
        activities = self.get_recent_activities(weeks)
        weekly = {}
        for act in activities:
            date_str = act.get("startTimeLocal", "")[:10]
            try:
                act_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            # Lundi de la semaine
            week_start = act_date - timedelta(days=act_date.weekday())
            key = week_start.strftime("%Y-%m-%d")
            km = (act.get("distance") or 0) / 1000
            weekly[key] = weekly.get(key, 0) + km
        # Trier par date
        return dict(sorted(weekly.items()))
