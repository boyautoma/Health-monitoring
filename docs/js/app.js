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

// Store chart instances for destroy/recreate
let chartInstances = {};
let chartsRendered = {};

// ── Navigation ──────────────────────────────

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const target = btn.dataset.page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(target).classList.add('active');

        if (target === 'pageTrends' && !chartsRendered.trends) renderTrends(7);
        if (target === 'pageSleep'  && !chartsRendered.sleep)  renderSleepTab(7);
        if (target === 'pagePerf'   && !chartsRendered.perf)   renderPerfCharts();
    });
});

// ── Range Pills — Trends ────────────────────

document.getElementById('trendsRangePills').addEventListener('click', function(e) {
    const pill = e.target.closest('.pill');
    if (!pill) return;
    this.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    const days = parseInt(pill.dataset.days, 10);
    renderTrends(days);
});

// ── Range Pills — Sleep ─────────────────────

document.getElementById('sleepRangePills').addEventListener('click', function(e) {
    const pill = e.target.closest('.pill');
    if (!pill) return;
    this.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    const days = parseInt(pill.dataset.days, 10);
    renderSleepTab(days);
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
    const r = await fetch(url + '?v=' + Date.now());
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

// Garmin Training Readiness feedback codes -> French
const READINESS_FEEDBACK = {
    BOOSTED_BY_GOOD_SLEEP: 'Boosté par un bon sommeil',
    TIME_TO_SLOW_DOWN: 'Lève le pied',
    POOR_HRV_UNBALANCED: 'HRV déséquilibrée',
    GOOD_HRV: 'Bonne HRV',
    HIGH_RECOVERY_TIME: 'Récup encore en cours',
    FULLY_RECOVERED: 'Pleinement récupéré',
    READY_TO_TRAIN: 'Prêt à t\'entraîner',
};

function readinessDisplay(score) {
    // Garmin Training Readiness color/label by score band
    if (score == null)  return { text: 'Readiness indispo', color: '#555' };
    if (score >= 75)    return { text: 'Prêt — fais ta séance', color: COLORS.green };
    if (score >= 50)    return { text: 'Modéré — séance ok, gère', color: COLORS.gold };
    if (score >= 25)    return { text: 'Fatigué — easy seulement', color: COLORS.orange };
    return { text: 'Repos recommandé', color: COLORS.red };
}

function renderRecovery(c) {
    const rec = c.recovery || {};
    // Garmin's own Training Readiness is the headline; fall back to custom score
    const garmin = rec.garmin_readiness;
    const useGarmin = garmin != null;
    const score = useGarmin ? garmin : rec.score;
    const level = useGarmin ? readinessDisplay(garmin) : (LEVELS[rec.level] || LEVELS.unknown);

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
    // Prefer Garmin's own feedback phrase if present
    let statusText = level.text;
    if (useGarmin && rec.readiness_feedback && READINESS_FEEDBACK[rec.readiness_feedback]) {
        statusText = READINESS_FEEDBACK[rec.readiness_feedback];
    }
    document.getElementById('heroStatus').textContent = statusText;
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

    // Stats row — show recovery time remaining (Garmin) instead of duplicate readiness
    setText('readinessVal', rec.recovery_time_h != null ? rec.recovery_time_h + 'h' : '--');
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
    // Try Garmin VO2max first, then estimate from running data
    const p = c.profile || {};
    const garminVo2 = p.vo2max;

    if (garminVo2 != null) {
        document.getElementById('perfVo2').textContent = Math.round(garminVo2);
        document.getElementById('perfVma').textContent = (garminVo2 / 3.5).toFixed(1);
        document.getElementById('perfVdot').textContent = Math.round(garminVo2);
    } else {
        // Estimate VDOT from best recent running performance
        estimateVdot();
    }
}

// ── VDOT / VO2max Estimation ───────────────

const FC_MAX = 198;
const FC_REPOS = 53;

function estimateVdot() {
    const acts = DATA.activities || [];
    const now = new Date();
    const msInDay = 86400000;

    // Find running activities in last 180 days with pace + HR data
    const candidates = acts.filter(a => {
        if (a.type !== 'running' || !a.avg_pace || !a.distance_km || a.distance_km < 3) return false;
        const daysAgo = (now - new Date(a.date)) / msInDay;
        return daysAgo <= 180;
    });

    if (!candidates.length) return;

    let bestVdot = 0;
    let bestAct = null;
    const hrEstimates = [];

    candidates.forEach(a => {
        const parts = a.avg_pace.split(':').map(Number);
        const paceSecPerKm = parts[0] * 60 + parts[1];
        const timeSec = paceSecPerKm * a.distance_km;
        const timeMin = timeSec / 60;
        const distMeters = a.distance_km * 1000;
        const velocity = distMeters / timeMin;

        // Jack Daniels oxygen cost at this pace
        const vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity;

        // Method 1: Pure VDOT (assumes race effort)
        const pctVo2max = 0.8 + 0.1894393 * Math.exp(-0.012778 * timeMin)
                        + 0.2989558 * Math.exp(-0.1932605 * timeMin);
        const vdot = vo2 / pctVo2max;
        if (vdot > bestVdot) { bestVdot = vdot; bestAct = a; }

        // Method 2: HR-based VO2max (Swain: %HRR ~ %VO2R)
        // Better for training runs since it accounts for sub-maximal effort
        if (a.avg_hr && a.avg_hr > FC_REPOS + 0.7 * (FC_MAX - FC_REPOS)) {
            // Only use efforts > 70% HRR (hard enough to be reliable)
            const hrrPct = (a.avg_hr - FC_REPOS) / (FC_MAX - FC_REPOS);
            const vo2max_hr = vo2 / hrrPct;
            if (vo2max_hr > 25 && vo2max_hr < 70) {
                hrEstimates.push({ vo2max: vo2max_hr, act: a, hr: a.avg_hr });
            }
        }
    });

    // Choose best method
    let finalVo2, method, sourceAct;

    if (hrEstimates.length >= 3) {
        // Use 75th percentile of HR-based estimates (robust, ignores outliers)
        hrEstimates.sort((a, b) => b.vo2max - a.vo2max);
        const idx = Math.floor(hrEstimates.length * 0.25);
        const best = hrEstimates[idx];
        finalVo2 = Math.round(best.vo2max * 10) / 10;
        sourceAct = best.act;
        method = 'HR';
    } else if (bestVdot > 0) {
        finalVo2 = Math.round(bestVdot * 10) / 10;
        sourceAct = bestAct;
        method = 'VDOT';
    } else {
        return;
    }

    const vma = (finalVo2 / 3.5).toFixed(1);

    document.getElementById('perfVo2').textContent = finalVo2.toFixed(0);
    document.getElementById('perfVma').textContent = vma;
    const vdotEl = document.getElementById('perfVdot');
    if (vdotEl) vdotEl.textContent = Math.round(bestVdot);

    const src = document.getElementById('refSource');
    if (src && sourceAct) {
        const hrInfo = method === 'HR' ? ' FC ' + Math.round(sourceAct.avg_hr) : '';
        src.textContent = sourceAct.distance_km + 'km @ ' + sourceAct.avg_pace + '/km' + hrInfo
            + ' (' + fmtDateFull(sourceAct.date) + ')';
    }
}

// ── Charts ──────────────────────────────────

function destroyChart(key) {
    if (chartInstances[key]) {
        chartInstances[key].destroy();
        delete chartInstances[key];
    }
}

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

function stackedBarOpts(unit) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true, position: 'bottom',
                labels: {
                    color: '#999', boxWidth: 10, boxHeight: 10,
                    font: { size: 10, family: 'Inter' }, padding: 12,
                    usePointStyle: true, pointStyle: 'rectRounded',
                },
            },
            tooltip: {
                backgroundColor: '#1a1a1a',
                titleColor: '#fff',
                bodyColor: '#999',
                borderColor: 'rgba(255,255,255,0.08)',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
                callbacks: {
                    label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} ${unit}`,
                },
            },
        },
        scales: {
            x: {
                stacked: true,
                grid: { display: false },
                ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxRotation: 0, maxTicksLimit: 7 },
                border: { display: false },
            },
            y: {
                stacked: true,
                grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false },
                ticks: { font: { size: 9, family: 'Inter' }, color: '#444', maxTicksLimit: 5 },
                border: { display: false },
            },
        },
    };
}

function makeGradient(ctx, color) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.parentElement?.offsetHeight || 140);
    g.addColorStop(0, color + '30');
    g.addColorStop(1, color + '00');
    return g;
}

function createLine(canvasId, labels, data, unit, color, chartKey) {
    const el = document.getElementById(canvasId);
    if (!el || !data.length) return null;
    const ctx = el.getContext('2d');
    const chart = new Chart(ctx, {
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
    if (chartKey) chartInstances[chartKey] = chart;
    return chart;
}

function createBar(canvasId, labels, data, unit, color, chartKey) {
    const el = document.getElementById(canvasId);
    if (!el || !data.length) return null;
    const ctx = el.getContext('2d');
    const chart = new Chart(ctx, {
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
    if (chartKey) chartInstances[chartKey] = chart;
    return chart;
}

function createStackedBar(canvasId, labels, datasets, unit, chartKey) {
    const el = document.getElementById(canvasId);
    if (!el) return null;
    const ctx = el.getContext('2d');
    const chart = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: stackedBarOpts(unit),
    });
    if (chartKey) chartInstances[chartKey] = chart;
    return chart;
}

// ── Filter History by Days ──────────────────

function filterHistory(days) {
    const h = (DATA.history || []).slice().reverse();
    if (!h.length) return [];
    if (days === 0) return h; // all
    return h.slice(-days);
}

// ── Trends Tab ──────────────────────────────

function renderTrends(days) {
    if (days == null) days = 7;

    // Update label
    const label = document.getElementById('trendsRangeLabel');
    if (label) {
        label.textContent = days === 0 ? 'Toutes les données' : `${days} derniers jours`;
    }

    // Destroy existing charts
    destroyChart('recovChart');
    destroyChart('hrvChart');
    destroyChart('rhrChart');
    destroyChart('stressChart');

    const h = filterHistory(days);
    if (!h.length) return;

    const dates = h.map(d => fmtDate(d.date));

    createLine('recovChart',  dates, h.map(d => d.recovery_score),  '/100', COLORS.green, 'recovChart');
    createLine('hrvChart',    dates, h.map(d => d.hrv_7day_avg),    'ms',   COLORS.teal,  'hrvChart');
    createLine('rhrChart',    dates, h.map(d => d.rhr),             'bpm',  COLORS.orange, 'rhrChart');
    createLine('stressChart', dates, h.map(d => d.stress_avg),      '/100', COLORS.red,    'stressChart');

    chartsRendered.trends = true;
}

// ── Sleep Tab ───────────────────────────────

function renderSleepTab(days) {
    if (days == null) days = 7;

    const titleEl = document.getElementById('sleepChartTitle');
    if (titleEl) {
        titleEl.textContent = days === 0
            ? 'Score sommeil — toutes les données'
            : `Score sommeil — ${days} jours`;
    }

    destroyChart('sleepChart');

    const h = filterHistory(days);
    if (!h.length) return;

    const dates = h.map(d => fmtDate(d.date));
    createLine('sleepChart', dates, h.map(d => d.sleep_score), '/100', COLORS.purple, 'sleepChart');

    renderSleepInsights();
    renderSleepHistory(h);

    chartsRendered.sleep = true;
}

// ── Sleep Insights Engine ──────────────

function renderSleepInsights() {
    const container = document.getElementById('sleepInsights');
    if (!container) return;

    const allHistory = (DATA.history || []).filter(d => d.sleep_score != null);
    if (allHistory.length < 3) {
        container.innerHTML = '';
        return;
    }

    const n = allHistory.length;
    const confidence = n >= 30 ? 'high' : n >= 14 ? 'medium' : 'low';
    const confLabel = confidence === 'high' ? 'Fiable' : confidence === 'medium' ? 'Modéré' : 'Faible';
    const confPct = Math.min(99, Math.round(50 + (n / 90) * 49));

    // Best bedtime
    const bestBedtime = findOptimalTime(allHistory, 'bedtime');
    // Best wake time
    const bestWake = findOptimalTime(allHistory, 'wake_time');
    // Optimal duration
    const bestDuration = findOptimalDuration(allHistory);
    // Deep sleep ratio analysis
    const deepAnalysis = analyzeDeepSleep(allHistory);
    // Recommendations
    const recos = generateRecos(allHistory, bestBedtime, bestWake, bestDuration, deepAnalysis);

    container.innerHTML = `
        <div class="insights-title">Analyse du sommeil</div>
        <div class="insights-grid">
            <div class="insight-card">
                <span class="insight-icon">🌙</span>
                <span class="insight-label">Coucher optimal</span>
                <span class="insight-value">${bestBedtime.time || '--'}</span>
                <span class="insight-sub">Score moy. ${bestBedtime.avgScore || '--'}/100</span>
                <span class="insight-confidence ${confidence}">${confPct}% · ${confLabel} (${n} nuits)</span>
            </div>
            <div class="insight-card">
                <span class="insight-icon">☀️</span>
                <span class="insight-label">Lever optimal</span>
                <span class="insight-value">${bestWake.time || '--'}</span>
                <span class="insight-sub">Score moy. ${bestWake.avgScore || '--'}/100</span>
                <span class="insight-confidence ${confidence}">${confPct}% · ${confLabel}</span>
            </div>
            <div class="insight-card">
                <span class="insight-icon">⏱️</span>
                <span class="insight-label">Durée optimale</span>
                <span class="insight-value">${bestDuration.label || '--'}</span>
                <span class="insight-sub">Score moy. ${bestDuration.avgScore || '--'}/100</span>
                <span class="insight-confidence ${confidence}">${confPct}% · ${confLabel}</span>
            </div>
            <div class="insight-card">
                <span class="insight-icon">💤</span>
                <span class="insight-label">Sommeil profond</span>
                <span class="insight-value">${deepAnalysis.avgPct}%</span>
                <span class="insight-sub">${deepAnalysis.avgMin} min/nuit · idéal 15-25%</span>
                <span class="insight-confidence ${deepAnalysis.status}">${deepAnalysis.statusText}</span>
            </div>
        </div>
        <div class="insight-reco">
            ${recos.map(r => `
                <div class="insight-reco-item">
                    <span class="reco-icon">${r.icon}</span>
                    <span>${r.text}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function findOptimalTime(history, field) {
    const buckets = {};
    history.forEach(d => {
        const t = d[field];
        if (!t) return;
        const hour = t.split(':')[0];
        if (!buckets[hour]) buckets[hour] = { scores: [], times: [] };
        buckets[hour].scores.push(d.sleep_score);
        buckets[hour].times.push(t);
    });

    if (Object.keys(buckets).length === 0) return { time: null, avgScore: null };

    let bestHour = null, bestAvg = 0;
    for (const [hour, b] of Object.entries(buckets)) {
        if (b.scores.length < 2) continue;
        const avg = b.scores.reduce((s, v) => s + v, 0) / b.scores.length;
        if (avg > bestAvg) { bestAvg = avg; bestHour = hour; }
    }

    if (!bestHour) {
        // Fallback: use the most frequent hour
        const sorted = Object.entries(buckets).sort((a, b) => b[1].scores.length - a[1].scores.length);
        bestHour = sorted[0][0];
        bestAvg = sorted[0][1].scores.reduce((s, v) => s + v, 0) / sorted[0][1].scores.length;
    }

    // Avg minute within that hour
    const times = buckets[bestHour].times;
    const avgMin = Math.round(times.reduce((s, t) => s + parseInt(t.split(':')[1], 10), 0) / times.length);
    return {
        time: `${bestHour}:${String(avgMin).padStart(2, '0')}`,
        avgScore: Math.round(bestAvg),
    };
}

function findOptimalDuration(history) {
    // Bucket into 30-min ranges
    const buckets = {};
    history.forEach(d => {
        if (!d.sleep_duration_min) return;
        const bucket = Math.floor(d.sleep_duration_min / 30) * 30;
        if (!buckets[bucket]) buckets[bucket] = [];
        buckets[bucket].push(d.sleep_score);
    });

    let bestBucket = null, bestAvg = 0;
    for (const [bucket, scores] of Object.entries(buckets)) {
        if (scores.length < 2) continue;
        const avg = scores.reduce((s, v) => s + v, 0) / scores.length;
        if (avg > bestAvg) { bestAvg = avg; bestBucket = parseInt(bucket, 10); }
    }

    if (bestBucket == null) return { label: null, avgScore: null };

    const lo = bestBucket, hi = bestBucket + 30;
    return {
        label: `${fmtMin(lo)}-${fmtMin(hi)}`,
        avgScore: Math.round(bestAvg),
    };
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

    // Bedtime consistency
    const bedtimes = history.filter(d => d.bedtime).map(d => {
        const [h, m] = d.bedtime.split(':').map(Number);
        return h * 60 + m;
    });
    if (bedtimes.length >= 7) {
        const avg = bedtimes.reduce((s, v) => s + v, 0) / bedtimes.length;
        const variance = Math.sqrt(bedtimes.reduce((s, v) => s + (v - avg) ** 2, 0) / bedtimes.length);
        if (variance > 60) {
            recos.push({ icon: '⏰', text: `Ton heure de coucher varie beaucoup (±${Math.round(variance)} min). Essaie de te coucher à la même heure chaque soir pour améliorer la qualité.` });
        } else {
            recos.push({ icon: '✅', text: `Bonne régularité de coucher (±${Math.round(variance)} min). Continue comme ça.` });
        }
    }

    // Score trend
    if (avgScore7 != null) {
        const older = history.slice(7, 14);
        const avgOlder = older.length ? Math.round(older.reduce((s, d) => s + d.sleep_score, 0) / older.length) : null;
        if (avgOlder != null) {
            const diff = avgScore7 - avgOlder;
            if (diff < -5) {
                recos.push({ icon: '📉', text: `Score en baisse (${avgScore7} vs ${avgOlder} la semaine précédente). Vérifie ton stress et ton heure de coucher.` });
            } else if (diff > 5) {
                recos.push({ icon: '📈', text: `Score en hausse (${avgScore7} vs ${avgOlder}). Ta routine actuelle fonctionne bien.` });
            }
        }
    }

    // Deep sleep
    if (deep.avgPct !== '--' && deep.avgPct < 15) {
        recos.push({ icon: '🧊', text: `Sommeil profond bas (${deep.avgPct}%). Essaie de réduire l'alcool et les écrans avant le coucher, et garde une chambre fraîche (18-19°C).` });
    }

    // Duration
    if (bedtime.time && duration.label) {
        recos.push({ icon: '🎯', text: `Pour un score optimal, couche-toi vers ${bedtime.time} et vise ${duration.label} de sommeil.` });
    }

    // Fallback if no recos
    if (!recos.length) {
        recos.push({ icon: '💡', text: 'Continue à collecter des données pour des recommandations plus précises.' });
    }

    return recos;
}

function renderSleepHistory(historyData) {
    const container = document.getElementById('sleepHistory');
    if (!container) return;

    // Remove old night cards (keep the title)
    const oldCards = container.querySelectorAll('.sleep-night-card');
    oldCards.forEach(c => c.remove());

    // Show last N nights (most recent first)
    const nights = historyData.slice().reverse().slice(0, 14);

    nights.forEach(d => {
        const deep  = d.deep_sleep_min  || 0;
        const light = d.light_sleep_min || 0;
        const rem   = d.rem_sleep_min   || 0;
        const awake = d.awake_min       || 0;
        const total = deep + light + rem + awake || 1;
        const durMin = d.sleep_duration_min || total;

        const card = document.createElement('div');
        card.className = 'sleep-night-card';
        card.innerHTML = `
            <div class="sleep-night-top">
                <span class="sleep-night-date">${fmtDateFull(d.date)}</span>
                <span class="sleep-night-dur">${fmtMin(durMin)}</span>
                <span class="sleep-night-score">${d.sleep_score != null ? d.sleep_score : '--'}<small>/100</small></span>
            </div>
            <div class="sleep-night-bar">
                <div class="sn-seg sn-deep" style="width:${(deep/total*100).toFixed(1)}%"></div>
                <div class="sn-seg sn-light" style="width:${(light/total*100).toFixed(1)}%"></div>
                <div class="sn-seg sn-rem" style="width:${(rem/total*100).toFixed(1)}%"></div>
                <div class="sn-seg sn-awake" style="width:${(awake/total*100).toFixed(1)}%"></div>
            </div>
        `;
        container.appendChild(card);
    });
}

// ── Performance Tab ─────────────────────────

function renderPerfCharts() {
    renderVolumeChart();
    initVolumeToggles();
    renderTrainingBanner();
    renderWeeklyRecap();
    renderActivitiesList();

    chartsRendered.perf = true;
}

function initVolumeToggles() {
    const wrap = document.getElementById('volToggles');
    if (!wrap) return;
    wrap.addEventListener('click', (e) => {
        const btn = e.target.closest('.vol-tog');
        if (!btn) return;
        btn.classList.toggle('active');
        renderVolumeChart();
    });
}

function renderTrainingBanner() {
    // Combined ACWR + Mech Stress in one banner
    const acts = DATA.activities || [];
    if (!acts.length) return;

    const now = new Date();
    const msInDay = 86400000;
    let acute = 0, chronic28 = 0;
    acts.forEach(a => {
        const d = new Date(a.date);
        const daysAgo = (now - d) / msInDay;
        const stress = a.mechanical_stress || 0;
        if (daysAgo <= 7) acute += stress;
        if (daysAgo <= 28) chronic28 += stress;
    });

    const chronicWeekly = chronic28 / 4;
    const acwr = chronicWeekly > 0 ? acute / chronicWeekly : 0;

    // ACWR value
    const valEl = document.getElementById('acwrValue');
    if (valEl) valEl.textContent = acwr.toFixed(2);

    // Marker
    const markerEl = document.getElementById('acwrMarker');
    if (markerEl) {
        const pct = Math.min(100, Math.max(0, (acwr / 2.0) * 100));
        markerEl.style.left = pct + '%';
        let markerColor;
        if (acwr >= 0.8 && acwr <= 1.3) markerColor = COLORS.green;
        else if ((acwr >= 0.6 && acwr < 0.8) || (acwr > 1.3 && acwr <= 1.5)) markerColor = COLORS.orange;
        else markerColor = COLORS.red;
        markerEl.style.backgroundColor = markerColor;
    }

    // Status
    const statusEl = document.getElementById('acwrStatus');
    const banner = document.getElementById('loadBanner');
    let zoneClass = 'zone-safe';
    if (statusEl) {
        if (acwr >= 0.8 && acwr <= 1.3) {
            statusEl.textContent = 'Zone optimale';
            statusEl.style.color = COLORS.green;
            zoneClass = 'zone-safe';
        } else if ((acwr >= 0.6 && acwr < 0.8) || (acwr > 1.3 && acwr <= 1.5)) {
            statusEl.textContent = 'Attention';
            statusEl.style.color = COLORS.orange;
            zoneClass = 'zone-warn';
        } else if (acwr < 0.6) {
            statusEl.textContent = 'Desentrainement';
            statusEl.style.color = COLORS.red;
            zoneClass = 'zone-danger';
        } else {
            statusEl.textContent = 'Surcharge';
            statusEl.style.color = COLORS.red;
            zoneClass = 'zone-danger';
        }
    }
    if (banner) {
        banner.classList.remove('zone-safe', 'zone-warn', 'zone-danger');
        banner.classList.add(zoneClass);
    }

    // Mech stress (weekly)
    const v = DATA.volumes || {};
    const vKeys = Object.keys(v).sort();
    let currStress = 0, prevStress = 0;
    if (vKeys.length) {
        const cw = v[vKeys[vKeys.length - 1]];
        if (typeof cw === 'object' && cw !== null) currStress = cw.weekly_mechanical_stress || 0;
        if (vKeys.length > 1) {
            const pw = v[vKeys[vKeys.length - 2]];
            if (typeof pw === 'object' && pw !== null) prevStress = pw.weekly_mechanical_stress || 0;
        }
    }
    if (currStress === 0) {
        acts.forEach(a => {
            const d = new Date(a.date);
            const daysAgo = (now - d) / msInDay;
            if (daysAgo <= 7) currStress += (a.mechanical_stress || 0);
            if (daysAgo > 7 && daysAgo <= 14) prevStress += (a.mechanical_stress || 0);
        });
    }

    const mechVal = document.getElementById('mechStressVal');
    if (mechVal) mechVal.textContent = Math.round(currStress);

    const trendEl = document.getElementById('mechStressTrend');
    if (trendEl && prevStress > 0) {
        const change = ((currStress - prevStress) / prevStress * 100);
        if (change > 5) {
            trendEl.textContent = '↑' + Math.round(change) + '%';
            trendEl.style.color = COLORS.orange;
        } else if (change < -5) {
            trendEl.textContent = '↓' + Math.round(Math.abs(change)) + '%';
            trendEl.style.color = COLORS.green;
        } else {
            trendEl.textContent = '~ stable';
            trendEl.style.color = COLORS.gold;
        }
    }
}

function renderWeeklyRecap() {
    const container = document.getElementById('weeklyRecap');
    if (!container) return;
    container.innerHTML = '';

    const types = [
        { key: 'running',  icon: '🏃' },
        { key: 'walking',  icon: '🚶' },
        { key: 'cycling',  icon: '🚴' },
    ];

    // Get current & previous week data
    let currByType = { running: 0, walking: 0, cycling: 0 };
    let prevByType = { running: 0, walking: 0, cycling: 0 };
    let totalCurr = 0, totalPrev = 0;

    const v = DATA.volumes || {};
    const vKeys = Object.keys(v).sort();
    const isNewFormat = vKeys.length > 0 && typeof v[vKeys[0]] === 'object';

    if (isNewFormat && vKeys.length > 0) {
        const cw = v[vKeys[vKeys.length - 1]];
        types.forEach(t => { currByType[t.key] = cw[t.key] || 0; });
        totalCurr = cw.total || types.reduce((s, t) => s + currByType[t.key], 0);
        if (vKeys.length > 1) {
            const pw = v[vKeys[vKeys.length - 2]];
            types.forEach(t => { prevByType[t.key] = pw[t.key] || 0; });
            totalPrev = pw.total || types.reduce((s, t) => s + prevByType[t.key], 0);
        }
    } else {
        // Fallback: compute from activities
        const acts = DATA.activities || [];
        const now = new Date();
        const msInDay = 86400000;
        acts.forEach(a => {
            const d = new Date(a.date);
            const daysAgo = (now - d) / msInDay;
            const t = (a.type || 'running').toLowerCase();
            const dist = a.distance_km || 0;
            if (daysAgo <= 7) { if (t in currByType) currByType[t] += dist; totalCurr += dist; }
            else if (daysAgo <= 14) { if (t in prevByType) prevByType[t] += dist; totalPrev += dist; }
        });
    }

    // Build sport pills
    types.forEach(t => {
        const curr = currByType[t.key];
        const prev = prevByType[t.key];
        const change = prev > 0 ? ((curr - prev) / prev * 100) : (curr > 0 ? 100 : 0);
        let changeClass = 'flat', changeText = '—';
        if (Math.abs(change) >= 1) {
            if (change > 0) { changeClass = 'up'; changeText = '+' + Math.round(change) + '%'; }
            else { changeClass = 'down'; changeText = Math.round(change) + '%'; }
        }

        const pill = document.createElement('div');
        pill.className = 'week-sport';
        pill.innerHTML = `
            <span class="week-sport-icon">${t.icon}</span>
            <span class="week-sport-vol">${curr.toFixed(1)}</span>
            <span class="week-sport-unit">km</span>
            <span class="week-sport-change ${changeClass}">${changeText}</span>
        `;
        container.appendChild(pill);
    });

    // Total pill
    const totalChange = totalPrev > 0 ? ((totalCurr - totalPrev) / totalPrev * 100) : (totalCurr > 0 ? 100 : 0);
    let totalClass = 'flat', totalText = '—';
    if (Math.abs(totalChange) >= 1) {
        if (totalChange > 0) { totalClass = 'up'; totalText = '+' + Math.round(totalChange) + '%'; }
        else { totalClass = 'down'; totalText = Math.round(totalChange) + '%'; }
    }
    const totalPill = document.createElement('div');
    totalPill.className = 'week-total';
    totalPill.innerHTML = `
        <span class="week-total-val">${totalCurr.toFixed(1)}</span>
        <span class="week-total-label">total km</span>
        <span class="week-sport-change ${totalClass}">${totalText}</span>
    `;
    container.appendChild(totalPill);
}

/* renderACWR and renderMechStress merged into renderTrainingBanner above */

function renderVolumeChart() {
    destroyChart('volumeChart');

    const v = DATA.volumes || {};
    const vKeys = Object.keys(v).sort();
    if (!vKeys.length) return;

    // Determine which sports are toggled on
    const toggles = document.querySelectorAll('#volToggles .vol-tog.active');
    const activeSports = Array.from(toggles).map(b => b.dataset.sport);
    if (!activeSports.length) {
        // Nothing selected — show empty
        const totalEl = document.getElementById('volTotal');
        if (totalEl) totalEl.textContent = '0 km';
        return;
    }

    const isNewFormat = typeof v[vKeys[0]] === 'object' && v[vKeys[0]] !== null;

    // Show last 16 weeks max for readability
    const displayKeys = vKeys.slice(-16);
    const labels = displayKeys.map(k => fmtDate(k));

    // Compute combined volume per week
    const combined = displayKeys.map(k => {
        if (isNewFormat) {
            return activeSports.reduce((sum, s) => sum + (v[k][s] || 0), 0);
        }
        return typeof v[k] === 'number' ? v[k] : 0;
    });

    // Current week total for header
    const currentTotal = combined[combined.length - 1] || 0;
    const totalEl = document.getElementById('volTotal');
    if (totalEl) totalEl.textContent = currentTotal.toFixed(1) + ' km';

    // Build gradient color from active sports
    let lineColor = COLORS.green;
    if (activeSports.length === 1) {
        if (activeSports[0] === 'walking') lineColor = COLORS.orange;
        else if (activeSports[0] === 'cycling') lineColor = COLORS.purple;
    } else {
        lineColor = COLORS.teal; // combined = teal
    }

    const el = document.getElementById('volumeChart');
    if (!el) return;
    const ctx = el.getContext('2d');

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: combined,
                borderColor: lineColor,
                backgroundColor: makeGradient(ctx, lineColor),
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 12,
                borderWidth: 2,
            }],
        },
        options: {
            ...chartOpts('km', lineColor),
            plugins: {
                ...chartOpts('km', lineColor).plugins,
                legend: { display: false },
            },
        },
    });
    chartInstances['volumeChart'] = chart;
}

function renderActivitiesList() {
    const acts = (DATA.activities || []).slice(0, 30);
    const list = document.getElementById('activitiesList');
    if (!list) return;

    // Remove old rows (keep the header)
    const oldRows = list.querySelectorAll('.activity-row');
    oldRows.forEach(r => r.remove());

    // Show count
    const countEl = document.getElementById('actCount');
    if (countEl) countEl.textContent = (DATA.activities || []).length + ' total';

    acts.forEach(a => {
        const type = (a.type || 'running').toLowerCase();

        const row = document.createElement('div');
        row.className = 'activity-row type-' + getActivityClass(type);

        // Build stats
        let statsHtml = `<span class="activity-dist">${a.distance_km != null ? a.distance_km + ' km' : '--'}</span>`;

        if (type === 'running') {
            statsHtml += `<span class="activity-pace">${a.avg_pace || '--'}/km</span>`;
        } else if (type === 'cycling') {
            const speed = a.avg_speed_kmh != null ? a.avg_speed_kmh.toFixed(1) + ' km/h' : '--';
            statsHtml += `<span class="activity-pace">${speed}</span>`;
        }
        if (a.elevation_gain) {
            statsHtml += `<span class="activity-elev">${a.elevation_gain}m D+</span>`;
        }

        const stress = a.mechanical_stress != null ? Math.round(a.mechanical_stress) : null;
        const stressClass = stress == null ? '' : stress >= 70 ? 'stress-high' : stress >= 40 ? 'stress-med' : 'stress-low';
        const stressBadge = stress != null ? `<span class="activity-stress ${stressClass}">${stress}</span>` : '';

        // Shortened name (remove location prefix if redundant)
        let name = a.name || getActivityName(type);
        if (name.length > 28) name = name.substring(0, 26) + '...';

        row.innerHTML = `
            <div class="activity-main">
                <div class="activity-name">${name}</div>
                <div class="activity-date-text">${fmtDateFull(a.date)}</div>
            </div>
            <div class="activity-stats">
                ${statsHtml}
            </div>
            ${stressBadge}
        `;
        list.appendChild(row);
    });
}

function getActivityEmoji(type) {
    switch (type) {
        case 'running': return '🏃';
        case 'walking': return '🚶';
        case 'cycling': return '🚴';
        default:        return '⚡';
    }
}

function getActivityClass(type) {
    switch (type) {
        case 'running': return 'running';
        case 'walking': return 'walking';
        case 'cycling': return 'cycling';
        default:        return 'other';
    }
}

function getActivityName(type) {
    switch (type) {
        case 'running': return 'Course';
        case 'walking': return 'Marche';
        case 'cycling': return 'Vélo';
        default:        return 'Activité';
    }
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

// ── Manual Sync ────────────────────────────

(function() {
    const btn = document.getElementById('syncBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        let token = localStorage.getItem('gh_pat');
        if (!token) {
            token = prompt(
                'GitHub Personal Access Token (une seule fois)\n\n' +
                'Pour le créer :\n' +
                '1. github.com → Settings → Developer settings\n' +
                '2. Fine-grained tokens → Generate new token\n' +
                '3. Repository: Health-monitoring uniquement\n' +
                '4. Permission Actions: Read and Write\n' +
                '5. Coller le token ici'
            );
            if (!token) return;
            localStorage.setItem('gh_pat', token.trim());
            token = token.trim();
        }

        btn.className = 'sync-btn syncing';

        try {
            const res = await fetch(
                'https://api.github.com/repos/boyautoma/Health-monitoring/actions/workflows/sync.yml/dispatches',
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Accept': 'application/vnd.github+json',
                    },
                    body: JSON.stringify({ ref: 'main' }),
                }
            );

            if (res.status === 204) {
                btn.className = 'sync-btn success';
                setTimeout(() => { btn.className = 'sync-btn'; }, 3000);
            } else if (res.status === 401 || res.status === 403) {
                localStorage.removeItem('gh_pat');
                btn.className = 'sync-btn error';
                setTimeout(() => { btn.className = 'sync-btn'; }, 3000);
                alert('Token invalide ou expiré. Clique à nouveau pour en saisir un nouveau.');
            } else {
                btn.className = 'sync-btn error';
                setTimeout(() => { btn.className = 'sync-btn'; }, 3000);
                alert(`Erreur ${res.status}: ${res.statusText}`);
            }
        } catch (e) {
            btn.className = 'sync-btn error';
            setTimeout(() => { btn.className = 'sync-btn'; }, 3000);
            alert('Erreur réseau: ' + e.message);
        }
    });
})();

// ── Init ────────────────────────────────────

loadData();
