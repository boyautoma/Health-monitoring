/* === AppCoach — Dashboard Logic (Global / Vélo / Course / Récup) === */

const CIRC_HERO  = 2 * Math.PI * 96;
const CIRC_SM    = 2 * Math.PI * 26;
const CIRC_MED   = 2 * Math.PI * 68;
const CIRC_READY = 2 * Math.PI * 50;

const COLORS = {
    green:  '#00f19f', teal: '#00d4aa', orange: '#ff8c42',
    purple: '#7c5cfc', red: '#ff4655', blue: '#4ea8de', gold: '#ffd700',
};

// HR zones CALIBRÉES (LTHR vélo 173) — doit matcher config.py
const HR_ZONES = [
    { key: 'Z1', name: 'Récup',     min: 0,   max: 140, color: COLORS.blue },
    { key: 'Z2', name: 'Endurance', min: 140, max: 155, color: COLORS.green },
    { key: 'Z3', name: 'Tempo',     min: 155, max: 162, color: COLORS.gold },
    { key: 'Z4', name: 'Seuil',     min: 162, max: 173, color: COLORS.orange },
    { key: 'Z5', name: 'VO2max',    min: 173, max: 999, color: COLORS.red },
];
function zoneOf(hr) {
    for (const z of HR_ZONES) if (hr < z.max) return z;
    return HR_ZONES[HR_ZONES.length - 1];
}

const READINESS_FEEDBACK = {
    BOOSTED_BY_GOOD_SLEEP: 'Boosté par un bon sommeil',
    TIME_TO_SLOW_DOWN: 'Lève le pied',
    POOR_HRV_UNBALANCED: 'HRV déséquilibrée',
    GOOD_HRV: 'Bonne HRV',
    HIGH_RECOVERY_TIME: 'Récup encore en cours',
    FULLY_RECOVERED: 'Pleinement récupéré',
    READY_TO_TRAIN: "Prêt à t'entraîner",
};

const LEVELS = {
    excellent: { text: 'Récupération excellente', color: COLORS.green },
    moderate:  { text: 'Récupération modérée',    color: COLORS.gold  },
    low:       { text: 'Récupération insuffisante', color: COLORS.orange },
    critical:  { text: 'Récupération critique',   color: COLORS.red   },
    unknown:   { text: 'Données indisponibles',   color: '#555' },
};

let chartInstances = {};
let chartsRendered = {};
let DATA = {};

// ── Navigation ──────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const target = btn.dataset.page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(target).classList.add('active');

        if (target === 'pageVelo'   && !chartsRendered.velo)   renderVelo();
        if (target === 'pageCourse' && !chartsRendered.course) renderCourse();
        if (target === 'pageRecup'  && !chartsRendered.recup)  renderRecup();
    });
});

// ── Range Pills — Récup trends ──────────────
document.getElementById('trendsRangePills').addEventListener('click', function(e) {
    const pill = e.target.closest('.pill');
    if (!pill) return;
    this.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    renderTrends(parseInt(pill.dataset.days, 10));
});

// ── Data Loading ────────────────────────────
async function loadData() {
    try {
        const [current, history, activities, volumes] = await Promise.all([
            fetchJSON('data/current.json'),
            fetchJSON('data/history.json'),
            fetchJSON('data/activities.json'),
            fetchJSON('data/weekly_volumes.json'),
        ]);
        DATA = { current, history, activities: dedupeActivities(activities), volumes };
        render();
    } catch (e) {
        console.error('Failed to load data:', e);
    }
}
async function fetchJSON(url) {
    const r = await fetch(url + '?v=' + Date.now());
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
}

// Remove legacy duplicate activities (same day/type/distance, some lack activityId).
// Prevents double-counted volume and duplicate feed rows.
function dedupeActivities(acts) {
    const map = new Map();
    const richness = x => (x.activityId ? 2 : 0) + (x.avg_hr ? 1 : 0);
    for (const a of acts || []) {
        const key = `${a.date}|${a.type}|${(a.distance_km || 0).toFixed(1)}|${a.duration_min || 0}`;
        const ex = map.get(key);
        if (!ex || richness(a) > richness(ex)) map.set(key, a);
    }
    return Array.from(map.values()).sort((x, y) => (x.date < y.date ? 1 : -1));
}

function render() {
    const c = DATA.current;
    if (!c) return;
    renderHeader(c);
    renderGlobal(c);   // active tab on load
}

function renderHeader(c) {
    const d = new Date(c.last_sync);
    document.getElementById('syncTime').textContent =
        d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

// ════════════════════════════════════════════
//  SHARED DATA HELPERS
// ════════════════════════════════════════════

function weekKeyOf(dateStr) {
    const [y, m, dd] = dateStr.split('-').map(Number);
    const d = new Date(y, m - 1, dd);
    const off = (d.getDay() + 6) % 7;       // days since Monday
    d.setDate(d.getDate() - off);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Weekly aggregates for a sport type, from activities
function weeklyByType(type) {
    const acts = (DATA.activities || []).filter(a => a.type === type);
    const map = {};
    acts.forEach(a => {
        if (!a.date) return;
        const wk = weekKeyOf(a.date);
        if (!map[wk]) map[wk] = { week: wk, km: 0, min: 0, dplus: 0, count: 0, stress: 0 };
        map[wk].km    += a.distance_km || 0;
        map[wk].min   += a.duration_min || 0;
        map[wk].dplus += a.elevation_gain || 0;
        map[wk].count += 1;
        map[wk].stress += a.mechanical_stress || 0;
    });
    return Object.values(map).sort((x, y) => x.week < y.week ? -1 : 1);
}

// Activities of a sport within a specific week (Monday key)
function activitiesInWeek(type, weekKey) {
    return (DATA.activities || []).filter(a => a.type === type && a.date && weekKeyOf(a.date) === weekKey);
}

// HR zone distribution from an arbitrary list of activities
function zoneStatsFromActs(acts) {
    const byZone = { Z1: 0, Z2: 0, Z3: 0, Z4: 0, Z5: 0 };
    let count = 0;
    acts.forEach(a => { if (a.avg_hr) { byZone[zoneOf(a.avg_hr).key] += a.duration_min || 0; count++; } });
    const total = Object.values(byZone).reduce((s, v) => s + v, 0);
    const easy = byZone.Z1 + byZone.Z2;
    const hard = byZone.Z3 + byZone.Z4 + byZone.Z5;
    return {
        byZone, total, count,
        easyPct: total ? Math.round(easy / total * 100) : 0,
        hardPct: total ? Math.round(hard / total * 100) : 0,
    };
}

// Label for a week (Monday..Sunday), tags the current week
function weekRangeLabel(weekKey) {
    const [y, m, d] = weekKey.split('-').map(Number);
    const mon = new Date(y, m - 1, d), sun = new Date(y, m - 1, d + 6);
    const f = dt => dt.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
    const now = weekKeyOf(new Date().toISOString().slice(0, 10));
    return `${f(mon)} – ${f(sun)}${weekKey === now ? ' · cette sem.' : ''}`;
}

// Update a week navigator's label + button states
function setupWeekNav(prefix, weeks, idx) {
    const label = document.getElementById(prefix + 'WeekLabel');
    const prev = document.getElementById(prefix + 'Prev');
    const next = document.getElementById(prefix + 'Next');
    if (!weeks.length) {
        if (label) label.textContent = 'Aucune donnée';
        if (prev) prev.disabled = true;
        if (next) next.disabled = true;
        return;
    }
    if (label) label.textContent = weekRangeLabel(weeks[idx].week);
    if (prev) prev.disabled = idx <= 0;
    if (next) next.disabled = idx >= weeks.length - 1;
}

// Render a feed from a given (already filtered/sorted) activity list
function renderFeedFromActs(containerId, acts, countId) {
    const list = document.getElementById(containerId);
    if (!list) return;
    list.querySelectorAll('.activity-row').forEach(r => r.remove());
    if (countId) {
        const el = document.getElementById(countId);
        if (el) el.textContent = acts.length + ' séance' + (acts.length > 1 ? 's' : '');
    }
    if (acts.length) list.insertAdjacentHTML('beforeend', acts.map(activityRowHTML).join(''));
    else list.insertAdjacentHTML('beforeend', '<div class="activity-row"><div class="activity-main"><div class="activity-name" style="color:var(--text-3)">Aucune séance cette semaine</div></div></div>');
}

// ACWR + weekly mechanical-stress for one sport
function sportLoad(type) {
    const acts = (DATA.activities || []).filter(a => a.type === type);
    const now = new Date(); const day = 86400000;
    let acute = 0, chronic = 0, prev = 0;
    acts.forEach(a => {
        const ago = (now - new Date(a.date)) / day;
        const s = a.mechanical_stress || 0;
        if (ago <= 7) acute += s;
        if (ago <= 28) chronic += s;
        if (ago > 7 && ago <= 14) prev += s;
    });
    const chronicW = chronic / 4;
    return { acwr: chronicW > 0 ? acute / chronicW : 0, curr: acute, prev };
}

function activityRowHTML(a) {
    const type = (a.type || 'running').toLowerCase();
    let stats = `<span class="activity-dist">${a.distance_km != null ? a.distance_km + ' km' : '--'}</span>`;
    if (type === 'running' || type === 'walking') stats += `<span class="activity-pace">${a.avg_pace || '--'}/km</span>`;
    else if (type === 'cycling') stats += `<span class="activity-pace">${a.avg_speed_kmh != null ? a.avg_speed_kmh.toFixed(1) + ' km/h' : '--'}</span>`;
    if (a.avg_hr) stats += `<span class="activity-hr">${Math.round(a.avg_hr)} bpm</span>`;
    if (a.elevation_gain) stats += `<span class="activity-elev">${Math.round(a.elevation_gain)}m D+</span>`;
    const stress = a.mechanical_stress != null ? Math.round(a.mechanical_stress) : null;
    const sClass = stress == null ? '' : stress >= 70 ? 'stress-high' : stress >= 40 ? 'stress-med' : 'stress-low';
    const badge = stress != null ? `<span class="activity-stress ${sClass}">${stress}</span>` : '';
    let name = a.name || getActivityName(type);
    if (name.length > 28) name = name.substring(0, 26) + '…';
    return `<div class="activity-row type-${getActivityClass(type)}">
        <div class="activity-main"><div class="activity-name">${name}</div><div class="activity-date-text">${fmtDateFull(a.date)}</div></div>
        <div class="activity-stats">${stats}</div>${badge}</div>`;
}

function renderFeed(containerId, type, limit, countId) {
    const list = document.getElementById(containerId);
    if (!list) return;
    list.querySelectorAll('.activity-row').forEach(r => r.remove());
    const acts = (DATA.activities || []).filter(a => !type || a.type === type).slice(0, limit);
    if (countId) {
        const total = (DATA.activities || []).filter(a => !type || a.type === type).length;
        const el = document.getElementById(countId);
        if (el) el.textContent = total + ' total';
    }
    list.insertAdjacentHTML('beforeend', acts.map(activityRowHTML).join(''));
}

// ════════════════════════════════════════════
//  GLOBAL TAB
// ════════════════════════════════════════════

function renderGlobal(c) {
    const rec = c.recovery || {};
    const d = new Date(c.date);
    document.getElementById('globalDate').textContent =
        d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });

    // Readiness
    const ready = rec.garmin_readiness;
    const disp = readinessDisplay(ready);
    setText('gReadyScore', ready != null ? ready : '--');
    const arc = document.getElementById('gReadyArc');
    arc.style.strokeDashoffset = CIRC_READY * (1 - (ready != null ? Math.min(100, ready) / 100 : 0));
    arc.style.stroke = disp.color;
    const lvl = document.getElementById('gReadyLevel');
    lvl.textContent = rec.readiness_level || '--';
    lvl.style.color = disp.color;
    document.getElementById('gReadyFeedback').textContent =
        (rec.readiness_feedback && READINESS_FEEDBACK[rec.readiness_feedback]) || disp.text;
    document.getElementById('gReadyTime').textContent =
        rec.recovery_time_h != null ? `Récup restante : ${rec.recovery_time_h}h` : '';

    // Advice of the day
    renderAdvice(ready, rec);

    // Quick metrics
    setText('gHrv', rec.hrv_last_night);
    const hs = document.getElementById('gHrvStatus');
    hs.textContent = rec.hrv_status === 'BALANCED' ? 'équilibrée' : rec.hrv_status === 'UNBALANCED' ? 'déséquilibrée' : '--';
    hs.style.color = rec.hrv_status === 'BALANCED' ? COLORS.green : rec.hrv_status === 'UNBALANCED' ? COLORS.orange : COLORS.text;
    setText('gSleep', rec.sleep_score);
    setText('gRhr', rec.rhr);
    setText('gStress', rec.stress_avg);

    // This week per sport
    renderWeekStrip('globalWeek');

    // Last activity
    const last = (DATA.activities || [])[0];
    const lastEl = document.getElementById('globalLastAct');
    if (last && lastEl) lastEl.innerHTML = activityRowHTML(last);

    // Aerobic form
    const p = c.profile || {};
    setText('gVo2', p.vo2max != null ? Math.round(p.vo2max) : '--');
    setText('gVma', p.vma != null ? p.vma.toFixed(1) : '--');
    setText('gVdot', p.vdot != null ? Math.round(p.vdot) : '--');

    chartsRendered.global = true;
}

function readinessDisplay(score) {
    if (score == null)  return { text: 'Readiness indispo', color: '#555' };
    if (score >= 75)    return { text: "Prêt — fais ta séance", color: COLORS.green };
    if (score >= 50)    return { text: 'Modéré — séance ok, gère', color: COLORS.gold };
    if (score >= 25)    return { text: 'Fatigué — easy seulement', color: COLORS.orange };
    return { text: 'Repos recommandé', color: COLORS.red };
}

function renderAdvice(ready, rec) {
    const el = document.getElementById('gAdvice');
    if (!el) return;
    let icon, title, msg, cls;
    if (ready == null) { icon = '⏳'; title = 'Readiness indisponible'; msg = 'Synchronise ta montre pour le calcul du jour.'; cls = 'neutral'; }
    else if (ready >= 75) { icon = '🟢'; title = 'Feu vert'; msg = 'Tu peux faire ta séance clé du jour (intensité ou sortie longue).'; cls = 'good'; }
    else if (ready >= 50) { icon = '🟡'; title = 'Modéré'; msg = 'Séance possible mais reste raisonnable — privilégie l\'endurance Z2.'; cls = 'warn'; }
    else if (ready >= 25) { icon = '🟠'; title = 'Fatigué'; msg = 'Easy / Z2 seulement aujourd\'hui. Pas d\'intensité.'; cls = 'warn'; }
    else { icon = '🔴'; title = 'Repos'; msg = 'Ton corps encaisse encore. Repos ou récup active (marche, mobilité).'; cls = 'danger'; }
    el.className = 'advice-card ' + cls;
    el.innerHTML = `<span class="advice-icon">${icon}</span>
        <div class="advice-body"><span class="advice-title">${title}</span><span class="advice-msg">${msg}</span></div>`;
}

// Per-sport weekly volume pills (current vs previous week)
function renderWeekStrip(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    const sports = [
        { key: 'running', icon: '🏃' },
        { key: 'walking', icon: '🚶' },
        { key: 'cycling', icon: '🚴' },
    ];
    let totalCurr = 0, totalPrev = 0;
    sports.forEach(s => {
        const wk = weeklyByType(s.key);
        const curr = wk.length ? wk[wk.length - 1].km : 0;
        const prev = wk.length > 1 ? wk[wk.length - 2].km : 0;
        // only count current week if last entry is the actual current week
        const thisWeek = weekKeyOf(new Date().toISOString().slice(0, 10));
        const currKm = (wk.length && wk[wk.length - 1].week === thisWeek) ? curr : 0;
        const prevKm = (wk.length && wk[wk.length - 1].week === thisWeek) ? prev : (wk.length ? curr : 0);
        totalCurr += currKm; totalPrev += prevKm;
        const change = prevKm > 0 ? ((currKm - prevKm) / prevKm * 100) : (currKm > 0 ? 100 : 0);
        let cc = 'flat', ct = '—';
        if (Math.abs(change) >= 1) { cc = change > 0 ? 'up' : 'down'; ct = (change > 0 ? '+' : '') + Math.round(change) + '%'; }
        container.insertAdjacentHTML('beforeend',
            `<div class="week-sport"><span class="week-sport-icon">${s.icon}</span>
             <span class="week-sport-vol">${currKm.toFixed(1)}</span><span class="week-sport-unit">km</span>
             <span class="week-sport-change ${cc}">${ct}</span></div>`);
    });
    const tc = totalPrev > 0 ? ((totalCurr - totalPrev) / totalPrev * 100) : 0;
    let tcc = 'flat', tct = '—';
    if (Math.abs(tc) >= 1) { tcc = tc > 0 ? 'up' : 'down'; tct = (tc > 0 ? '+' : '') + Math.round(tc) + '%'; }
    container.insertAdjacentHTML('beforeend',
        `<div class="week-total"><span class="week-total-val">${totalCurr.toFixed(1)}</span>
         <span class="week-total-label">total km</span><span class="week-sport-change ${tcc}">${tct}</span></div>`);
}

// ════════════════════════════════════════════
//  VÉLO TAB
// ════════════════════════════════════════════

let veloWeeks = [], veloIdx = 0, veloNavWired = false;

function renderVelo() {
    veloWeeks = weeklyByType('cycling');           // weeks with ≥1 ride, ascending
    veloIdx = Math.max(0, veloWeeks.length - 1);   // default = most recent week with a ride
    if (!veloNavWired) {
        document.getElementById('veloPrev').addEventListener('click', () => { if (veloIdx > 0) { veloIdx--; renderVeloWeek(); } });
        document.getElementById('veloNext').addEventListener('click', () => { if (veloIdx < veloWeeks.length - 1) { veloIdx++; renderVeloWeek(); } });
        veloNavWired = true;
    }
    renderVeloWeek();
    // Volume trend (16wk) + current load — context, not week-specific
    renderSportVol('veloVolChart', 'cycling', 'veloVolTotal', COLORS.purple, 'veloVol');
    renderSportLoad('cycling', { acwr: 'veloAcwr', status: 'veloAcwrStatus', marker: 'veloMarker',
        stress: 'veloStress', trend: 'veloStressTrend', banner: 'veloLoadBanner' });
    chartsRendered.velo = true;
}

function renderVeloWeek() {
    setupWeekNav('velo', veloWeeks, veloIdx);
    const w = veloWeeks.length ? veloWeeks[veloIdx] : { km: 0, min: 0, dplus: 0, count: 0, week: null };
    setText('veloKm', w.km.toFixed(0));
    setText('veloH', fmtMin(Math.round(w.min)));
    setText('veloDplus', Math.round(w.dplus));
    setText('veloCount', w.count);
    const acts = w.week ? activitiesInWeek('cycling', w.week) : [];
    renderZoneDistFromActs(acts, 'veloZoneBar', 'veloZoneLegend', 'veloZoneNote', 'veloPolar');
    renderFeedFromActs('veloFeed', acts, 'veloFeedCount');
}

// ════════════════════════════════════════════
//  COURSE TAB
// ════════════════════════════════════════════

let courseWeeks = [], courseIdx = 0, courseNavWired = false;

function renderCourse() {
    const c = DATA.current || {};
    const p = c.profile || {};
    setText('courseVo2', p.vo2max != null ? Math.round(p.vo2max) : '--');
    setText('courseVma', p.vma != null ? p.vma.toFixed(1) : '--');
    setText('courseVdot', p.vdot != null ? Math.round(p.vdot) : '--');
    const src = document.getElementById('courseRefSource');
    if (src) src.textContent = p.vdot_source || '';

    courseWeeks = weeklyByType('running');
    courseIdx = Math.max(0, courseWeeks.length - 1);
    if (!courseNavWired) {
        document.getElementById('coursePrev').addEventListener('click', () => { if (courseIdx > 0) { courseIdx--; renderCourseWeek(); } });
        document.getElementById('courseNext').addEventListener('click', () => { if (courseIdx < courseWeeks.length - 1) { courseIdx++; renderCourseWeek(); } });
        courseNavWired = true;
    }
    renderCourseWeek();
    renderSportVol('courseVolChart', 'running', 'courseVolTotal', COLORS.green, 'courseVol');
    renderStrengthReminder();
    chartsRendered.course = true;
}

function renderCourseWeek() {
    setupWeekNav('course', courseWeeks, courseIdx);
    const w = courseWeeks.length ? courseWeeks[courseIdx] : { km: 0, min: 0, dplus: 0, count: 0, week: null };
    setText('courseKm', w.km.toFixed(0));
    setText('courseH', fmtMin(Math.round(w.min)));
    setText('courseDplus', Math.round(w.dplus));
    setText('courseCount', w.count);
    const acts = w.week ? activitiesInWeek('running', w.week) : [];
    renderZoneDistFromActs(acts, 'courseZoneBar', 'courseZoneLegend', 'courseZoneNote', 'coursePolar');
    renderFeedFromActs('courseFeed', acts, 'courseFeedCount');
}

function renderStrengthReminder() {
    const el = document.getElementById('courseStrength');
    if (!el) return;
    const strg = (DATA.activities || []).filter(a => a.type === 'strength');
    let days = null;
    if (strg.length) days = Math.floor((new Date() - new Date(strg[0].date)) / 86400000);
    let icon, title, msg, cls;
    if (days == null) { icon = '💪'; title = 'Renforcement'; msg = 'Aucune séance enregistrée. Le renfo protège tes tibias (périostites).'; cls = 'danger'; }
    else if (days > 14) { icon = '⚠️'; title = `Renfo manqué depuis ${days}j`; msg = 'Plus de 2 semaines sans renforcement — risque accru de périostites. À reprendre.'; cls = 'danger'; }
    else if (days > 7) { icon = '💪'; title = `Renfo : ${days}j`; msg = 'Plus d\'une semaine sans renfo. Planifie une séance.'; cls = 'warn'; }
    else { icon = '✅'; title = `Renfo à jour (${days}j)`; msg = 'Bon rythme de renforcement. Continue.'; cls = 'good'; }
    el.className = 'advice-card ' + cls;
    el.innerHTML = `<span class="advice-icon">${icon}</span>
        <div class="advice-body"><span class="advice-title">${title}</span><span class="advice-msg">${msg}</span></div>`;
}

// ── Shared sport renderers ──

function renderSportVol(canvasId, type, totalId, color, key) {
    destroyChart(key);
    const wk = weeklyByType(type).slice(-16);
    if (!wk.length) return;
    const labels = wk.map(w => fmtDate(w.week));
    const data = wk.map(w => +w.km.toFixed(1));
    createLine(canvasId, labels, data, 'km', color, key);
    const totalEl = document.getElementById(totalId);
    if (totalEl) {
        const thisWeek = weekKeyOf(new Date().toISOString().slice(0, 10));
        const cur = wk[wk.length - 1].week === thisWeek ? wk[wk.length - 1].km : 0;
        totalEl.textContent = cur.toFixed(0) + ' km';
    }
}

function renderZoneDistFromActs(acts, barId, legendId, noteId, polarId) {
    const z = zoneStatsFromActs(acts);
    const bar = document.getElementById(barId);
    const legend = document.getElementById(legendId);
    const note = document.getElementById(noteId);
    const polar = document.getElementById(polarId);
    if (!z.total) {
        if (bar) bar.innerHTML = '';
        if (legend) legend.innerHTML = '<span class="zone-empty">Pas assez de données FC</span>';
        if (note) note.textContent = '';
        if (polar) polar.textContent = '';
        return;
    }
    // Bar segments
    bar.innerHTML = HR_ZONES.map(zn => {
        const pct = z.byZone[zn.key] / z.total * 100;
        return pct > 0 ? `<div class="zone-seg" style="width:${pct}%;background:${zn.color}"></div>` : '';
    }).join('');
    // Legend
    legend.innerHTML = HR_ZONES.map(zn => {
        const min = z.byZone[zn.key];
        const pct = Math.round(min / z.total * 100);
        return `<div class="zone-leg-item"><span class="zone-dot" style="background:${zn.color}"></span>
            <span class="zone-leg-name">${zn.key} ${zn.name}</span>
            <span class="zone-leg-pct">${pct}%</span><span class="zone-leg-min">${fmtMin(Math.round(min))}</span></div>`;
    }).join('');
    // Polarization tag
    polar.textContent = `${z.easyPct}% easy / ${z.hardPct}% dur`;
    const goodPolar = z.easyPct >= 70;
    polar.style.color = goodPolar ? COLORS.green : COLORS.orange;
    // Note vs 80/20
    if (z.easyPct >= 75) {
        note.textContent = `✅ Bonne polarisation (cible 80% easy). ${z.count} séances analysées.`;
        note.style.color = COLORS.green;
    } else {
        note.textContent = `⚠️ Trop d'intensité moyenne — cible 80% easy / 20% dur. Tu es à ${z.easyPct}% easy. (${z.count} séances)`;
        note.style.color = COLORS.orange;
    }
}

function renderSportLoad(type, ids) {
    const { acwr, curr, prev } = sportLoad(type);
    const valEl = document.getElementById(ids.acwr);
    if (valEl) valEl.textContent = acwr.toFixed(2);
    const marker = document.getElementById(ids.marker);
    if (marker) {
        marker.style.left = Math.min(100, Math.max(0, (acwr / 2.0) * 100)) + '%';
        marker.style.backgroundColor =
            (acwr >= 0.8 && acwr <= 1.3) ? COLORS.green :
            ((acwr >= 0.6 && acwr < 0.8) || (acwr > 1.3 && acwr <= 1.5)) ? COLORS.orange : COLORS.red;
    }
    const statusEl = document.getElementById(ids.status);
    const banner = document.getElementById(ids.banner);
    let zoneClass = 'zone-safe', txt, col;
    if (acwr >= 0.8 && acwr <= 1.3) { txt = 'Zone optimale'; col = COLORS.green; zoneClass = 'zone-safe'; }
    else if (acwr > 1.3 && acwr <= 1.5) { txt = 'Charge élevée'; col = COLORS.orange; zoneClass = 'zone-warn'; }
    else if (acwr >= 0.6 && acwr < 0.8) { txt = 'Sous-charge'; col = COLORS.orange; zoneClass = 'zone-warn'; }
    else if (acwr < 0.6) { txt = 'Désentraînement'; col = COLORS.red; zoneClass = 'zone-danger'; }
    else { txt = 'Surcharge'; col = COLORS.red; zoneClass = 'zone-danger'; }
    if (statusEl) { statusEl.textContent = txt; statusEl.style.color = col; }
    if (banner) { banner.classList.remove('zone-safe', 'zone-warn', 'zone-danger'); banner.classList.add(zoneClass); }
    const stressEl = document.getElementById(ids.stress);
    if (stressEl) stressEl.textContent = Math.round(curr);
    const trendEl = document.getElementById(ids.trend);
    if (trendEl && prev > 0) {
        const ch = (curr - prev) / prev * 100;
        if (ch > 5) { trendEl.textContent = '↑' + Math.round(ch) + '%'; trendEl.style.color = COLORS.orange; }
        else if (ch < -5) { trendEl.textContent = '↓' + Math.round(Math.abs(ch)) + '%'; trendEl.style.color = COLORS.green; }
        else { trendEl.textContent = '~ stable'; trendEl.style.color = COLORS.gold; }
    }
}

// ════════════════════════════════════════════
//  RÉCUP TAB
// ════════════════════════════════════════════

function renderRecup() {
    const c = DATA.current;
    if (!c) return;
    renderRecovery(c);
    renderTrends(7);
    renderSleepBlock(c);
    renderSleepInsights();
    renderSleepChart(7);
    chartsRendered.recup = true;
}

function renderRecovery(c) {
    const rec = c.recovery || {};
    const garmin = rec.garmin_readiness;
    const useGarmin = garmin != null;
    const score = useGarmin ? garmin : rec.score;
    const level = useGarmin ? readinessDisplay(garmin) : (LEVELS[rec.level] || LEVELS.unknown);

    const d = new Date(c.date);
    document.getElementById('heroDate').textContent =
        d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

    const arc = document.getElementById('heroArc');
    arc.style.strokeDashoffset = CIRC_HERO * (1 - (score != null ? Math.min(100, score) / 100 : 0));
    arc.style.stroke = level.color;
    document.getElementById('heroValue').textContent = score != null ? score : '--';
    let statusText = level.text;
    if (useGarmin && rec.readiness_feedback && READINESS_FEEDBACK[rec.readiness_feedback])
        statusText = READINESS_FEEDBACK[rec.readiness_feedback];
    const hs = document.getElementById('heroStatus');
    hs.textContent = statusText;
    hs.style.color = level.color;

    setMetricRing('hrvArc',    'hrvVal',    rec.hrv_7day_avg, 80, COLORS.teal);
    setMetricRing('rhrArc',    'rhrVal',    rec.rhr,          null, COLORS.orange, true);
    setMetricRing('sleepArc',  'sleepVal',  rec.sleep_score,  100, COLORS.purple);
    setMetricRing('stressArc', 'stressVal', rec.stress_avg,   100, COLORS.red, true);

    if (rec.hrv_7day_avg != null)
        document.getElementById('hrvSub').textContent = `moy. 7j · ${rec.hrv_last_night || '--'} nuit`;

    setText('readinessVal', rec.recovery_time_h != null ? rec.recovery_time_h + 'h' : '--');
    setText('hrv7Val', rec.hrv_7day_avg != null ? rec.hrv_7day_avg + 'ms' : '--');
    setText('sleepDurVal', rec.sleep_duration_min != null ? fmtMin(rec.sleep_duration_min) : '--');
}

function setMetricRing(arcId, valId, value, maxVal, color, inverted) {
    const arc = document.getElementById(arcId);
    const el = document.getElementById(valId);
    if (value == null) { el.textContent = '--'; return; }
    el.textContent = Math.round(value);
    let pct = inverted ? Math.max(0, 1 - value / (maxVal || 100)) : (maxVal ? Math.min(1, value / maxVal) : 0);
    arc.style.strokeDashoffset = CIRC_SM * (1 - pct);
}

function renderTrends(days) {
    if (days == null) days = 7;
    ['recovChart', 'hrvChart', 'rhrChart', 'stressChart'].forEach(destroyChart);
    const h = filterHistory(days);
    if (!h.length) return;
    const dates = h.map(d => fmtDate(d.date));
    // Readiness: prefer Garmin training_readiness, fall back to custom score where missing
    createLine('recovChart', dates, h.map(d => d.training_readiness != null ? d.training_readiness : d.recovery_score), '/100', COLORS.green, 'recovChart');
    createLine('hrvChart',   dates, h.map(d => d.hrv_7day_avg), 'ms',  COLORS.teal,  'hrvChart');
    createLine('rhrChart',   dates, h.map(d => d.rhr),          'bpm', COLORS.orange, 'rhrChart');
    createLine('stressChart',dates, h.map(d => d.stress_avg),   '/100',COLORS.red,    'stressChart');
}

function filterHistory(days) {
    const h = (DATA.history || []).slice().reverse();
    if (!h.length) return [];
    return days === 0 ? h : h.slice(-days);
}

function renderSleepBlock(c) {
    const rec = c.recovery || {};
    const score = rec.sleep_score;
    document.getElementById('sleepHeroArc').style.strokeDashoffset = CIRC_MED * (1 - (score != null ? Math.min(1, score / 100) : 0));
    document.getElementById('sleepScore').textContent = score != null ? score : '--';
    if (rec.sleep_duration_min != null)
        document.getElementById('sleepDuration').textContent = fmtMin(rec.sleep_duration_min) + ' de sommeil';
    const deep = rec.deep_sleep_min || 0, light = rec.light_sleep_min || 0, rem = rec.rem_sleep_min || 0, awake = rec.awake_min || 0;
    const total = deep + light + rem + awake || 1;
    document.getElementById('segDeep').style.width  = (deep / total * 100) + '%';
    document.getElementById('segLight').style.width = (light / total * 100) + '%';
    document.getElementById('segRem').style.width   = (rem / total * 100) + '%';
    document.getElementById('segAwake').style.width = (awake / total * 100) + '%';
    document.getElementById('legDeep').textContent  = fmtMin(deep);
    document.getElementById('legLight').textContent = fmtMin(light);
    document.getElementById('legRem').textContent   = fmtMin(rem);
    document.getElementById('legAwake').textContent = fmtMin(awake);
}

function renderSleepChart(days) {
    const titleEl = document.getElementById('sleepChartTitle');
    if (titleEl) titleEl.textContent = `Score sommeil — ${days} jours`;
    destroyChart('sleepChart');
    const h = filterHistory(days);
    if (!h.length) return;
    createLine('sleepChart', h.map(d => fmtDate(d.date)), h.map(d => d.sleep_score), '/100', COLORS.purple, 'sleepChart');
}

// ── Sleep Insights Engine (unchanged) ──
function renderSleepInsights() {
    const container = document.getElementById('sleepInsights');
    if (!container) return;
    const allHistory = (DATA.history || []).filter(d => d.sleep_score != null);
    if (allHistory.length < 3) { container.innerHTML = ''; return; }
    const n = allHistory.length;
    const confidence = n >= 30 ? 'high' : n >= 14 ? 'medium' : 'low';
    const confLabel = confidence === 'high' ? 'Fiable' : confidence === 'medium' ? 'Modéré' : 'Faible';
    const confPct = Math.min(99, Math.round(50 + (n / 90) * 49));
    const bestBedtime = findOptimalTime(allHistory, 'bedtime');
    const bestWake = findOptimalTime(allHistory, 'wake_time');
    const bestDuration = findOptimalDuration(allHistory);
    const deepAnalysis = analyzeDeepSleep(allHistory);
    const recos = generateRecos(allHistory, bestBedtime, bestWake, bestDuration, deepAnalysis);
    container.innerHTML = `
        <div class="insights-title">Analyse du sommeil</div>
        <div class="insights-grid">
            <div class="insight-card"><span class="insight-icon">🌙</span><span class="insight-label">Coucher optimal</span><span class="insight-value">${bestBedtime.time || '--'}</span><span class="insight-sub">Score moy. ${bestBedtime.avgScore || '--'}/100</span><span class="insight-confidence ${confidence}">${confPct}% · ${confLabel} (${n} nuits)</span></div>
            <div class="insight-card"><span class="insight-icon">☀️</span><span class="insight-label">Lever optimal</span><span class="insight-value">${bestWake.time || '--'}</span><span class="insight-sub">Score moy. ${bestWake.avgScore || '--'}/100</span><span class="insight-confidence ${confidence}">${confPct}% · ${confLabel}</span></div>
            <div class="insight-card"><span class="insight-icon">⏱️</span><span class="insight-label">Durée optimale</span><span class="insight-value">${bestDuration.label || '--'}</span><span class="insight-sub">Score moy. ${bestDuration.avgScore || '--'}/100</span><span class="insight-confidence ${confidence}">${confPct}% · ${confLabel}</span></div>
            <div class="insight-card"><span class="insight-icon">💤</span><span class="insight-label">Sommeil profond</span><span class="insight-value">${deepAnalysis.avgPct}%</span><span class="insight-sub">${deepAnalysis.avgMin} min/nuit · idéal 15-25%</span><span class="insight-confidence ${deepAnalysis.status}">${deepAnalysis.statusText}</span></div>
        </div>
        <div class="insight-reco">${recos.map(r => `<div class="insight-reco-item"><span class="reco-icon">${r.icon}</span><span>${r.text}</span></div>`).join('')}</div>`;
}
function findOptimalTime(history, field) {
    const buckets = {};
    history.forEach(d => { const t = d[field]; if (!t) return; const hour = t.split(':')[0];
        if (!buckets[hour]) buckets[hour] = { scores: [], times: [] }; buckets[hour].scores.push(d.sleep_score); buckets[hour].times.push(t); });
    if (Object.keys(buckets).length === 0) return { time: null, avgScore: null };
    let bestHour = null, bestAvg = 0;
    for (const [hour, b] of Object.entries(buckets)) { if (b.scores.length < 2) continue;
        const avg = b.scores.reduce((s, v) => s + v, 0) / b.scores.length; if (avg > bestAvg) { bestAvg = avg; bestHour = hour; } }
    if (!bestHour) { const sorted = Object.entries(buckets).sort((a, b) => b[1].scores.length - a[1].scores.length);
        bestHour = sorted[0][0]; bestAvg = sorted[0][1].scores.reduce((s, v) => s + v, 0) / sorted[0][1].scores.length; }
    const times = buckets[bestHour].times;
    const avgMin = Math.round(times.reduce((s, t) => s + parseInt(t.split(':')[1], 10), 0) / times.length);
    return { time: `${bestHour}:${String(avgMin).padStart(2, '0')}`, avgScore: Math.round(bestAvg) };
}
function findOptimalDuration(history) {
    const buckets = {};
    history.forEach(d => { if (!d.sleep_duration_min) return; const bucket = Math.floor(d.sleep_duration_min / 30) * 30;
        if (!buckets[bucket]) buckets[bucket] = []; buckets[bucket].push(d.sleep_score); });
    let bestBucket = null, bestAvg = 0;
    for (const [bucket, scores] of Object.entries(buckets)) { if (scores.length < 2) continue;
        const avg = scores.reduce((s, v) => s + v, 0) / scores.length; if (avg > bestAvg) { bestAvg = avg; bestBucket = parseInt(bucket, 10); } }
    if (bestBucket == null) return { label: null, avgScore: null };
    return { label: `${fmtMin(bestBucket)}-${fmtMin(bestBucket + 30)}`, avgScore: Math.round(bestAvg) };
}
function analyzeDeepSleep(history) {
    const valid = history.filter(d => d.deep_sleep_min != null && d.sleep_duration_min > 0);
    if (!valid.length) return { avgPct: '--', avgMin: '--', status: 'medium', statusText: 'Données insuffisantes' };
    const pcts = valid.map(d => (d.deep_sleep_min / d.sleep_duration_min) * 100);
    const avgPct = Math.round(pcts.reduce((s, v) => s + v, 0) / pcts.length);
    const avgMin = Math.round(valid.reduce((s, d) => s + d.deep_sleep_min, 0) / valid.length);
    let status, statusText;
    if (avgPct >= 15 && avgPct <= 25) { status = 'high'; statusText = 'Optimal'; }
    else if (avgPct >= 10 && avgPct < 15) { status = 'medium'; statusText = 'Légèrement bas'; }
    else if (avgPct > 25) { status = 'high'; statusText = 'Très bon'; }
    else { status = 'low'; statusText = 'Insuffisant'; }
    return { avgPct, avgMin, status, statusText };
}
function generateRecos(history, bedtime, wake, duration, deep) {
    const recos = [];
    const recent7 = history.slice(0, 7);
    const avgScore7 = recent7.length ? Math.round(recent7.reduce((s, d) => s + d.sleep_score, 0) / recent7.length) : null;
    const bedtimes = history.filter(d => d.bedtime).map(d => { const [h, m] = d.bedtime.split(':').map(Number); return h * 60 + m; });
    if (bedtimes.length >= 7) {
        const avg = bedtimes.reduce((s, v) => s + v, 0) / bedtimes.length;
        const variance = Math.sqrt(bedtimes.reduce((s, v) => s + (v - avg) ** 2, 0) / bedtimes.length);
        recos.push(variance > 60
            ? { icon: '⏰', text: `Ton heure de coucher varie beaucoup (±${Math.round(variance)} min). Vise un coucher régulier.` }
            : { icon: '✅', text: `Bonne régularité de coucher (±${Math.round(variance)} min). Continue.` });
    }
    if (avgScore7 != null) {
        const older = history.slice(7, 14);
        const avgOlder = older.length ? Math.round(older.reduce((s, d) => s + d.sleep_score, 0) / older.length) : null;
        if (avgOlder != null) { const diff = avgScore7 - avgOlder;
            if (diff < -5) recos.push({ icon: '📉', text: `Score en baisse (${avgScore7} vs ${avgOlder}). Vérifie stress et coucher.` });
            else if (diff > 5) recos.push({ icon: '📈', text: `Score en hausse (${avgScore7} vs ${avgOlder}). Ta routine fonctionne.` }); }
    }
    if (deep.avgPct !== '--' && deep.avgPct < 15) recos.push({ icon: '🧊', text: `Sommeil profond bas (${deep.avgPct}%). Réduis alcool/écrans, chambre fraîche (18-19°C).` });
    if (bedtime.time && duration.label) recos.push({ icon: '🎯', text: `Pour un score optimal : couche-toi vers ${bedtime.time} et vise ${duration.label}.` });
    if (!recos.length) recos.push({ icon: '💡', text: 'Continue à collecter des données pour des recommandations plus précises.' });
    return recos;
}

// ── Charts ──────────────────────────────────
function destroyChart(key) { if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; } }
function chartOpts(unit, color) {
    return {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
            tooltip: { backgroundColor: '#1a1a1a', titleColor: '#fff', bodyColor: '#999', borderColor: 'rgba(255,255,255,0.08)', borderWidth: 1, cornerRadius: 8, padding: 10,
                callbacks: { label: ctx => `${ctx.parsed.y} ${unit}` } } },
        scales: {
            x: { grid: { display: false }, ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxRotation: 0, maxTicksLimit: 7 }, border: { display: false } },
            y: { grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false }, ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxTicksLimit: 5 }, border: { display: false } } },
        elements: { point: { radius: 0, hoverRadius: 4, hoverBorderWidth: 2, hoverBackgroundColor: color, hoverBorderColor: '#111' }, line: { borderWidth: 2, tension: 0.4 } },
    };
}
function makeGradient(ctx, color) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.parentElement?.offsetHeight || 140);
    g.addColorStop(0, color + '30'); g.addColorStop(1, color + '00'); return g;
}
function createLine(canvasId, labels, data, unit, color, chartKey) {
    const el = document.getElementById(canvasId);
    if (!el || !data.length) return null;
    const ctx = el.getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: [{ data, borderColor: color, backgroundColor: makeGradient(ctx, color), fill: true, spanGaps: true }] },
        options: chartOpts(unit, color),
    });
    if (chartKey) chartInstances[chartKey] = chart;
    return chart;
}

// ── Activity helpers ──
function getActivityClass(type) { return ['running', 'walking', 'cycling'].includes(type) ? type : 'other'; }
function getActivityName(type) { return { running: 'Course', walking: 'Marche', cycling: 'Vélo' }[type] || 'Activité'; }

// ── Format helpers ──
function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val != null ? val : '--'; }
function fmtMin(min) { if (!min) return '0m'; const h = Math.floor(min / 60), m = Math.round(min % 60); return h > 0 ? `${h}h${String(m).padStart(2, '0')}` : `${m}m`; }
function fmtDate(dateStr) { if (!dateStr) return ''; const p = dateStr.split('-'); return `${p[2]}/${p[1]}`; }
function fmtDateFull(dateStr) { if (!dateStr) return ''; try { return new Date(dateStr).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }); } catch { return dateStr; } }

// ── Manual Sync button ──────────────────────
(function() {
    const btn = document.getElementById('syncBtn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        let token = localStorage.getItem('gh_pat');
        if (!token) {
            token = prompt('GitHub Personal Access Token (une seule fois)\n\nRepository: Health-monitoring · Permission Actions: Read and Write');
            if (!token) return;
            localStorage.setItem('gh_pat', token.trim()); token = token.trim();
        }
        btn.className = 'sync-btn syncing';
        try {
            const res = await fetch('https://api.github.com/repos/boyautoma/Health-monitoring/actions/workflows/sync.yml/dispatches',
                { method: 'POST', headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/vnd.github+json' }, body: JSON.stringify({ ref: 'main' }) });
            if (res.status === 204) { btn.className = 'sync-btn success'; setTimeout(() => btn.className = 'sync-btn', 3000); }
            else if (res.status === 401 || res.status === 403) { localStorage.removeItem('gh_pat'); btn.className = 'sync-btn error'; setTimeout(() => btn.className = 'sync-btn', 3000); alert('Token invalide. Reclique pour en saisir un nouveau.'); }
            else { btn.className = 'sync-btn error'; setTimeout(() => btn.className = 'sync-btn', 3000); alert(`Erreur ${res.status}`); }
        } catch (e) { btn.className = 'sync-btn error'; setTimeout(() => btn.className = 'sync-btn', 3000); alert('Erreur réseau: ' + e.message); }
    });
})();

// ── Init ──
loadData();
