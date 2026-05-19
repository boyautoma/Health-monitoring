/* === AppCoach — Dashboard Logic === */

const CIRC_HERO = 2 * Math.PI * 96;   // hero ring r=96
const CIRC_SM   = 2 * Math.PI * 26;   // small ring r=26
const CIRC_MED  = 2 * Math.PI * 68;   // sleep ring r=68

const COLORS = {
    green:  '#00f19f',
    teal:   '#00d4aa',
    orange: '#ff8c42',
    purple: '#7c5cfc',
    red:    '#ff4655',
    blue:   '#4ea8de',
    gold:   '#ffd700',
};

const LEVELS = {
    excellent: { text: 'Récupération excellente', color: COLORS.green },
    moderate:  { text: 'Récupération modérée',    color: COLORS.gold  },
    low:       { text: 'Récupération insuffisante', color: COLORS.orange },
    critical:  { text: 'Récupération critique',   color: COLORS.red   },
    unknown:   { text: 'Données indisponibles',   color: '#555' },
};

let chartsRendered = {};

// ── Navigation ──────────────────────────────

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const target = btn.dataset.page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(target).classList.add('active');

        if (target === 'pageTrends' && !chartsRendered.trends) renderTrends();
        if (target === 'pageSleep'  && !chartsRendered.sleep)  renderSleepChart();
        if (target === 'pagePerf'   && !chartsRendered.perf)   renderPerfCharts();
    });
});

// ── Data Loading ────────────────────────────

let DATA = {};

async function loadData() {
    try {
        const [current, history, activities, volumes] = await Promise.all([
            fetchJSON('data/current.json'),
            fetchJSON('data/history.json'),
            fetchJSON('data/activities.json'),
            fetchJSON('data/weekly_volumes.json'),
        ]);
        DATA = { current, history, activities, volumes };
        render();
    } catch (e) {
        console.error('Failed to load data:', e);
    }
}

async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
}

// ── Render ──────────────────────────────────

function render() {
    const c = DATA.current;
    if (!c) return;

    renderHeader(c);
    renderRecovery(c);
    renderSleep(c);
    renderPerf(c);
}

function renderHeader(c) {
    const d = new Date(c.last_sync);
    const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    document.getElementById('syncTime').textContent = time;
}

function renderRecovery(c) {
    const rec = c.recovery || {};
    const score = rec.score;
    const level = LEVELS[rec.level] || LEVELS.unknown;

    // Date
    const d = new Date(c.date);
    const opts = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
    document.getElementById('heroDate').textContent = d.toLocaleDateString('fr-FR', opts);

    // Hero ring
    const pct = score != null ? Math.min(100, score) / 100 : 0;
    const arc = document.getElementById('heroArc');
    arc.style.strokeDashoffset = CIRC_HERO * (1 - pct);
    arc.style.stroke = level.color;

    document.getElementById('heroValue').textContent = score != null ? score : '--';
    document.getElementById('heroStatus').textContent = level.text;
    document.getElementById('heroStatus').style.color = level.color;

    // Metric cards
    setMetricRing('hrvArc',    'hrvVal',    rec.hrv_7day_avg,  70, COLORS.teal);
    setMetricRing('rhrArc',    'rhrVal',    rec.rhr,           null, COLORS.orange, true);
    setMetricRing('sleepArc',  'sleepVal',  rec.sleep_score,   100, COLORS.purple);
    setMetricRing('stressArc', 'stressVal', rec.stress_avg,    100, COLORS.red, true);

    if (rec.hrv_7day_avg != null) {
        document.getElementById('hrvSub').textContent = `moy. 7j · ${rec.hrv_last_night || '--'} nuit`;
    }
    if (rec.sleep_duration_min != null) {
        const h = Math.floor(rec.sleep_duration_min / 60);
        const m = rec.sleep_duration_min % 60;
        document.getElementById('sleepSub').textContent = `${h}h${String(m).padStart(2, '0')}`;
    }

    // Stats row
    setText('readinessVal', rec.training_readiness);
    setText('vo2Val', c.profile?.vo2max != null ? Math.round(c.profile.vo2max) : '--');
    const vma = c.profile?.vo2max != null ? (c.profile.vo2max / 3.5).toFixed(1) : '--';
    setText('vmaVal', vma);
}

function setMetricRing(arcId, valId, value, maxVal, color, inverted) {
    const arc = document.getElementById(arcId);
    const el = document.getElementById(valId);
    if (value == null) {
        el.textContent = '--';
        return;
    }
    el.textContent = Math.round(value);

    let pct;
    if (inverted) {
        pct = maxVal ? Math.max(0, 1 - value / maxVal) : Math.max(0, 1 - value / 100);
    } else {
        pct = maxVal ? Math.min(1, value / maxVal) : 0;
    }
    arc.style.strokeDashoffset = CIRC_SM * (1 - pct);
}

function renderSleep(c) {
    const rec = c.recovery || {};
    document.getElementById('sleepDate').textContent = c.date || '--';

    // Score ring
    const score = rec.sleep_score;
    const pct = score != null ? Math.min(1, score / 100) : 0;
    document.getElementById('sleepHeroArc').style.strokeDashoffset = CIRC_MED * (1 - pct);
    document.getElementById('sleepScore').textContent = score != null ? score : '--';

    // Duration
    if (rec.sleep_duration_min != null) {
        const h = Math.floor(rec.sleep_duration_min / 60);
        const m = rec.sleep_duration_min % 60;
        document.getElementById('sleepDuration').textContent = `${h}h${String(m).padStart(2, '0')} de sommeil`;
    }

    // Stages
    const deep  = rec.deep_sleep_min  || 0;
    const light = rec.light_sleep_min || 0;
    const rem   = rec.rem_sleep_min   || 0;
    const awake = rec.awake_min       || 0;
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

function renderPerf(c) {
    const p = c.profile || {};
    document.getElementById('perfVo2').textContent = p.vo2max != null ? Math.round(p.vo2max) : '--';
    const vma = p.vo2max != null ? (p.vo2max / 3.5).toFixed(1) : '--';
    document.getElementById('perfVma').textContent = vma;
}

// ── Charts ──────────────────────────────────

function chartOpts(unit, color) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1a1a1a',
                titleColor: '#fff',
                bodyColor: '#999',
                borderColor: 'rgba(255,255,255,0.08)',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
                callbacks: {
                    label: ctx => `${ctx.parsed.y} ${unit}`,
                },
            },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxRotation: 0, maxTicksLimit: 7 },
                border: { display: false },
            },
            y: {
                grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxTicksLimit: 5 },
                border: { display: false },
            },
        },
        elements: {
            point: { radius: 0, hoverRadius: 4, hoverBorderWidth: 2, hoverBackgroundColor: color, hoverBorderColor: '#111' },
            line:  { borderWidth: 2, tension: 0.4 },
        },
    };
}

function makeGradient(ctx, color) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.parentElement?.offsetHeight || 140);
    g.addColorStop(0, color + '30');
    g.addColorStop(1, color + '00');
    return g;
}

function createLine(canvasId, labels, data, unit, color) {
    const el = document.getElementById(canvasId);
    if (!el || !data.length) return;
    const ctx = el.getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data,
                borderColor: color,
                backgroundColor: makeGradient(ctx, color),
                fill: true,
            }],
        },
        options: chartOpts(unit, color),
    });
}

function createBar(canvasId, labels, data, unit, color) {
    const el = document.getElementById(canvasId);
    if (!el || !data.length) return;
    const ctx = el.getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: color + '50',
                borderColor: color,
                borderWidth: 1,
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: chartOpts(unit, color),
    });
}

function renderTrends() {
    const h = (DATA.history || []).slice().reverse();
    if (!h.length) return;

    const dates = h.map(d => fmtDate(d.date));

    createLine('recovChart',  dates, h.map(d => d.recovery_score),  '/100', COLORS.green);
    createLine('hrvChart',    dates, h.map(d => d.hrv_7day_avg),    'ms',   COLORS.teal);
    createLine('rhrChart',    dates, h.map(d => d.rhr),             'bpm',  COLORS.orange);
    createLine('stressChart', dates, h.map(d => d.stress_avg),      '/100', COLORS.red);

    chartsRendered.trends = true;
}

function renderSleepChart() {
    const h = (DATA.history || []).slice().reverse();
    if (!h.length) return;
    const dates = h.map(d => fmtDate(d.date));
    createLine('sleepChart', dates, h.map(d => d.sleep_score), '/100', COLORS.purple);
    chartsRendered.sleep = true;
}

function renderPerfCharts() {
    // Volume
    const v = DATA.volumes || {};
    const vKeys = Object.keys(v);
    if (vKeys.length) {
        createBar('volumeChart', vKeys.map(k => fmtDate(k)), vKeys.map(k => v[k]), 'km', COLORS.blue);
    }

    // Activities
    const acts = (DATA.activities || []).slice(0, 15);
    const list = document.getElementById('activitiesList');
    acts.forEach(a => {
        const row = document.createElement('div');
        row.className = 'activity-row';
        row.innerHTML = `
            <div class="activity-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="5" r="3"/><path d="M6.5 8.5l3 3.5v7m5-7l-3-3.5M6 21l4-4m4 4l-2-4"/>
                </svg>
            </div>
            <div class="activity-main">
                <div class="activity-name">${a.name || 'Course'}</div>
                <div class="activity-date-text">${fmtDateFull(a.date)}</div>
            </div>
            <div class="activity-stats">
                <span class="activity-dist">${a.distance_km} km</span>
                <span class="activity-pace">${a.avg_pace || '--'}/km</span>
            </div>
        `;
        list.appendChild(row);
    });

    chartsRendered.perf = true;
}

// ── Helpers ─────────────────────────────────

function setText(id, val) {
    document.getElementById(id).textContent = val != null ? val : '--';
}

function fmtMin(min) {
    if (!min) return '0m';
    const h = Math.floor(min / 60);
    const m = min % 60;
    return h > 0 ? `${h}h${String(m).padStart(2, '0')}` : `${m}m`;
}

function fmtDate(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    return `${parts[2]}/${parts[1]}`;
}

function fmtDateFull(dateStr) {
    if (!dateStr) return '';
    try {
        return new Date(dateStr).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
    } catch {
        return dateStr;
    }
}

// ── Init ────────────────────────────────────

loadData();
