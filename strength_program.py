from datetime import datetime


# Programme de renforcement musculaire ciblé périostites + efficacité de course
# Matériel: Kettlebell 8kg + élastiques
EXERCISES = [
    {
        "id": "squat_gobelet",
        "name": "Squat gobelet (KB 8kg)",
        "sets": 3,
        "reps": "12",
        "rest_seconds": 60,
        "target": "Quadriceps, stabilité genou",
        "description": "KB contre la poitrine, descente lente (3s). Genoux alignés avec les pieds.",
        "priority": False,
        "category": "force",
    },
    {
        "id": "fente_arriere",
        "name": "Fente arrière",
        "sets": 3,
        "reps": "10/jambe",
        "rest_seconds": 60,
        "target": "Quadriceps, fessiers, équilibre G/D",
        "description": "Commencer par la jambe gauche (plus faible). Genou arrière frôle le sol.",
        "priority": False,
        "category": "force",
    },
    {
        "id": "pont_fessier",
        "name": "Pont fessier unilatéral",
        "sets": 3,
        "reps": "12/jambe",
        "rest_seconds": 45,
        "target": "Fessiers, stabilité bassin",
        "description": "Pied au sol, autre jambe tendue. Monter le bassin et tenir 2s en haut.",
        "priority": False,
        "category": "stabilite",
    },
    {
        "id": "mollet_excentrique",
        "name": "Montée de mollet excentrique ★",
        "sets": 3,
        "reps": "15",
        "rest_seconds": 45,
        "target": "Tibial antérieur, absorption des chocs",
        "description": "Sur une marche, monter sur 2 pieds, descendre TRÈS lentement sur 1 pied (4-5s). "
                       "EXERCICE PRIORITAIRE — ne jamais sauter cette séance.",
        "priority": True,
        "category": "periostite",
    },
    {
        "id": "elastique_abduction",
        "name": "Élastique abduction debout",
        "sets": 3,
        "reps": "15/jambe",
        "rest_seconds": 45,
        "target": "Stabilité hanche et genou",
        "description": "Élastique aux chevilles. Pas latéraux lents et contrôlés, 10 pas dans chaque direction.",
        "priority": False,
        "category": "stabilite",
    },
    {
        "id": "chaise_murale",
        "name": "Chaise murale",
        "sets": 3,
        "reps": "30 secondes",
        "rest_seconds": 45,
        "target": "Endurance quadriceps",
        "description": "Dos plaqué au mur, cuisses parallèles au sol. Maintenir la position.",
        "priority": False,
        "category": "force",
    },
    {
        "id": "toe_raises",
        "name": "Toe raises (tibial antérieur) ★",
        "sets": 3,
        "reps": "20",
        "rest_seconds": 30,
        "target": "Prévention directe périostites",
        "description": "Debout, lever les orteils vers le tibia. Lent et contrôlé. "
                       "EXERCICE PRIORITAIRE — renforce le muscle exact impliqué dans les périostites.",
        "priority": True,
        "category": "periostite",
    },
    {
        "id": "step_up",
        "name": "Step-up unilatéral",
        "sets": 3,
        "reps": "10/jambe",
        "rest_seconds": 60,
        "target": "Force fonctionnelle course",
        "description": "Sur une marche ou un banc. Monter sur 1 jambe sans pousser avec l'autre. "
                       "Commencer par la jambe gauche.",
        "priority": False,
        "category": "force",
    },
]


def get_program(week_number=1):
    """Retourne le programme de renforcement avec progression."""
    cycle_week = ((week_number - 1) % 4) + 1  # Cycle de 4 semaines
    exercises = []

    for ex in EXERCISES:
        exercise = dict(ex)

        # Progression semaine 3-4: augmenter charge/reps
        if cycle_week >= 3:
            if "/" in exercise["reps"]:
                # Ex: "10/jambe" -> "12/jambe"
                base_reps = int(exercise["reps"].split("/")[0])
                suffix = exercise["reps"].split("/")[1]
                new_reps = base_reps + 2
                exercise["reps"] = f"{new_reps}/{suffix}"
            elif "secondes" in exercise["reps"]:
                base_time = int(exercise["reps"].split(" ")[0])
                new_time = base_time + 10
                exercise["reps"] = f"{new_time} secondes"
            else:
                base_reps = int(exercise["reps"])
                exercise["reps"] = str(base_reps + 3)

        exercises.append(exercise)

    return {
        "week_number": week_number,
        "cycle_week": cycle_week,
        "exercises": exercises,
        "duration_min": 30,
        "notes": _get_week_notes(cycle_week),
    }


def _get_week_notes(cycle_week):
    if cycle_week <= 2:
        return "Programme de base — Focus sur la forme et le contrôle du mouvement."
    elif cycle_week == 3:
        return "Progression — Augmentation des reps/durées. Maintenir une exécution propre."
    else:
        return "Semaine de progression avancée — Si la charge devient trop facile, passer au KB plus lourd."


def get_session_summary():
    """Retourne un résumé du programme pour l'affichage dans le plan."""
    priority_exercises = [e for e in EXERCISES if e["priority"]]
    other_exercises = [e for e in EXERCISES if not e["priority"]]

    return {
        "title": "Renforcement musculaire (anti-périostite)",
        "duration_min": 30,
        "priority_exercises": [e["name"] for e in priority_exercises],
        "all_exercises": [e["name"] for e in EXERCISES],
        "categories": {
            "periostite": [e["name"] for e in EXERCISES if e["category"] == "periostite"],
            "force": [e["name"] for e in EXERCISES if e["category"] == "force"],
            "stabilite": [e["name"] for e in EXERCISES if e["category"] == "stabilite"],
        },
    }


def get_days_since_last_session(last_session_date):
    """Calcule le nombre de jours depuis la dernière séance."""
    if not last_session_date:
        return None
    try:
        if isinstance(last_session_date, str):
            last_date = datetime.strptime(last_session_date[:10], "%Y-%m-%d")
        else:
            last_date = last_session_date
        return (datetime.now() - last_date).days
    except (ValueError, TypeError):
        return None
