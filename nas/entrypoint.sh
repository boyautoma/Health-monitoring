#!/bin/bash
# AppCoach — sync Garmin depuis le NAS (IP maison = pas de ban Garmin).
# - Runs planifiés à 08:05 et 20:35 (heure de Paris)
# - Écoute les demandes manuelles du bouton dashboard (fichier .sync-request
#   sur GitHub, vérifié toutes les 60s)
# Totalement isolé : ne voit que /data. Aucun port ouvert.
set -u

REPO_DIR=/data/repo
TOKENS_DIR=/data/tokens
STATE_DIR=/data/state
REPO_URL="https://x-access-token:${GH_PAT}@github.com/boyautoma/Health-monitoring.git"
export API_REQ="https://api.github.com/repos/boyautoma/Health-monitoring/contents/.sync-request"
SLOTS="08:05 20:35"

log() { echo "[$(date '+%F %T')] $*"; }

# sha of the current manual-request file on GitHub ("" if absent/unreachable)
request_sha() {
python3 - <<'PY'
import os, json, urllib.request
req = urllib.request.Request(os.environ["API_REQ"], headers={
    "Authorization": "Bearer " + os.environ["GH_PAT"],
    "Accept": "application/vnd.github+json"})
try:
    print(json.load(urllib.request.urlopen(req, timeout=15)).get("sha", ""))
except Exception:
    print("")
PY
}

sync_once() {
    log "── sync start ──"

    if [ ! -d "$REPO_DIR/.git" ]; then
        log "premier lancement : clone du repo"
        git clone --quiet "$REPO_URL" "$REPO_DIR" || { log "ERREUR clone"; return 1; }
        git -C "$REPO_DIR" config user.name "appcoach-nas"
        git -C "$REPO_DIR" config user.email "appcoach-nas@users.noreply.github.com"
    fi
    git -C "$REPO_DIR" pull --rebase --quiet || log "WARN: pull a échoué, on continue"

    mkdir -p "$REPO_DIR/.garmin_tokens" "$TOKENS_DIR"
    if [ -f "$TOKENS_DIR/oauth1_token.json" ]; then
        cp "$TOKENS_DIR"/*.json "$REPO_DIR/.garmin_tokens/" 2>/dev/null
    else
        log "ERREUR: pas de tokens dans /data/tokens — copie oauth1_token.json et oauth2_token.json dedans"
        return 1
    fi

    ( cd "$REPO_DIR" && python sync_garmin.py --fast )
    rc=$?

    cp "$REPO_DIR"/.garmin_tokens/*.json "$TOKENS_DIR"/ 2>/dev/null

    if [ $rc -eq 0 ]; then
        git -C "$REPO_DIR" add docs/data/
        if ! git -C "$REPO_DIR" diff --staged --quiet; then
            git -C "$REPO_DIR" commit --quiet -m "sync: Garmin data $(date '+%F %H:%M') (NAS)"
            git -C "$REPO_DIR" push --quiet && log "sync OK — poussé" || log "ERREUR push"
        else
            log "sync OK — rien de neuf"
        fi
    else
        log "sync échouée (rc=$rc)"
    fi
}

mkdir -p "$STATE_DIR"

# Run de démarrage
sync_once

# Les créneaux déjà passés aujourd'hui sont marqués faits (le run de démarrage couvre)
for t in $SLOTS; do
    if [ "$(date +%s)" -ge "$(date -d "today $t" +%s)" ]; then
        date +%F > "$STATE_DIR/slot_${t/:/}"
    fi
done
# La demande manuelle en cours (s'il y en a une) est considérée traitée
request_sha > "$STATE_DIR/handled_request"

log "en veille — créneaux $SLOTS + écoute du bouton (60s)"

while true; do
    sleep 60

    # 1) Créneaux planifiés
    today=$(date +%F)
    for t in $SLOTS; do
        sf="$STATE_DIR/slot_${t/:/}"
        if [ "$(date +%s)" -ge "$(date -d "today $t" +%s)" ] && [ "$(cat "$sf" 2>/dev/null)" != "$today" ]; then
            log "run planifié ($t)"
            sync_once
            echo "$today" > "$sf"
        fi
    done

    # 2) Demande manuelle (bouton dashboard)
    sha=$(request_sha)
    handled=$(cat "$STATE_DIR/handled_request" 2>/dev/null || echo "")
    if [ -n "$sha" ] && [ "$sha" != "$handled" ]; then
        log "demande manuelle détectée (bouton dashboard)"
        sync_once
        echo "$sha" > "$STATE_DIR/handled_request"
    fi
done
