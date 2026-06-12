#!/bin/bash
# AppCoach — sync Garmin depuis le NAS (IP maison = pas de ban Garmin).
# Tourne à 08:05 et 20:35 heure de Paris. Totalement isolé : ne voit que /data.
set -u

REPO_DIR=/data/repo
TOKENS_DIR=/data/tokens
REPO_URL="https://x-access-token:${GH_PAT}@github.com/boyautoma/Health-monitoring.git"

log() { echo "[$(date '+%F %T')] $*"; }

sync_once() {
    log "── sync start ──"

    # Clone au premier lancement, sinon pull
    if [ ! -d "$REPO_DIR/.git" ]; then
        log "premier lancement : clone du repo"
        git clone --quiet "$REPO_URL" "$REPO_DIR" || { log "ERREUR clone"; return 1; }
        git -C "$REPO_DIR" config user.name "appcoach-nas"
        git -C "$REPO_DIR" config user.email "appcoach-nas@users.noreply.github.com"
    fi
    git -C "$REPO_DIR" pull --rebase --quiet || log "WARN: pull a échoué, on continue"

    # Tokens Garmin : copiés depuis le dossier persistant
    mkdir -p "$REPO_DIR/.garmin_tokens" "$TOKENS_DIR"
    if [ -f "$TOKENS_DIR/oauth1_token.json" ]; then
        cp "$TOKENS_DIR"/*.json "$REPO_DIR/.garmin_tokens/" 2>/dev/null
    else
        log "ERREUR: pas de tokens dans /data/tokens — copie oauth1_token.json et oauth2_token.json dedans"
        return 1
    fi

    # Sync rapide (~10s)
    ( cd "$REPO_DIR" && python sync_garmin.py --fast )
    rc=$?

    # Persister les tokens rafraîchis pour le prochain run
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

# Un run au démarrage, puis aux heures fixes
sync_once

while true; do
    now=$(date +%s)
    next=""
    for t in "08:05" "20:35"; do
        target=$(date -d "today $t" +%s)
        [ "$target" -le "$now" ] && target=$(date -d "tomorrow $t" +%s)
        if [ -z "$next" ] || [ "$target" -lt "$next" ]; then next=$target; fi
    done
    log "prochain run : $(date -d "@$next" '+%F %H:%M')"
    sleep $(( next - now ))
    sync_once
done
