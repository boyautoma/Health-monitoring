#!/bin/bash
# AppCoach — sync Garmin depuis le NAS (IP maison = jamais banni par Garmin).
# - Sync automatique toutes les 2h, toute la journée : attrape les données de
#   la nuit dès que ta montre les a envoyées à Garmin, peu importe ton heure de
#   lever. Tu n'as donc (quasi) jamais besoin du bouton manuel.
# - Écoute aussi les demandes du bouton dashboard (fichier .sync-request,
#   vérifié toutes les 60s).
# Totalement isolé : ne voit que /data. Aucun port ouvert.
set -u

REPO_DIR=/data/repo
TOKENS_DIR=/data/tokens
STATE_DIR=/data/state
REPO_URL="https://x-access-token:${GH_PAT}@github.com/boyautoma/Health-monitoring.git"
export API_REQ="https://api.github.com/repos/boyautoma/Health-monitoring/contents/.sync-request"
EVERY_SEC=7200          # sync auto toutes les 2 heures

log() { echo "[$(date '+%F %T')] $*"; }

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
        log "ERREUR: pas de tokens dans /data/tokens"
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

# Sync au démarrage
sync_once
last_auto=$(date +%s)
# La demande manuelle en cours (s'il y en a une) est considérée déjà traitée
request_sha > "$STATE_DIR/handled_request"

log "en veille — sync auto toutes les 2h + écoute du bouton (60s)"

while true; do
    sleep 60
    now=$(date +%s)

    # 1) Sync automatique toutes les 2h
    if [ $(( now - last_auto )) -ge $EVERY_SEC ]; then
        log "sync auto (intervalle 2h)"
        sync_once
        last_auto=$(date +%s)
    fi

    # 2) Demande manuelle (bouton dashboard)
    sha=$(request_sha)
    handled=$(cat "$STATE_DIR/handled_request" 2>/dev/null || echo "")
    if [ -n "$sha" ] && [ "$sha" != "$handled" ]; then
        log "demande manuelle détectée (bouton)"
        sync_once
        echo "$sha" > "$STATE_DIR/handled_request"
        last_auto=$(date +%s)
    fi
done
