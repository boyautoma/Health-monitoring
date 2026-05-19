/* === AppCoach — Chart.js Helpers (WHOOP Dark Theme) === */

function _yBounds(data, padding) {
    const vals = data.filter(v => v != null && !isNaN(v));
    if (vals.length === 0) return {};
    const mn = Math.min(...vals);
    const mx = Math.max(...vals);
    const range = mx - mn || 1;
    const pad = range * (padding || 0.15);
    return {
        suggestedMin: Math.floor(mn - pad),
        suggestedMax: Math.ceil(mx + pad),
    };
}

function _baseOptions(data, unit) {
    const bounds = _yBounds(data);
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1e1e3f',
                titleColor: '#e8e8f0',
                bodyColor: '#8888aa',
                borderColor: 'rgba(255,255,255,0.08)',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
                callbacks: {
                    label: (ctx) => `${ctx.parsed.y.toFixed(1)} ${unit}`,
                },
            },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { font: { size: 9 }, color: '#8080a0', maxRotation: 45 },
                border: { color: 'rgba(255,255,255,0.06)' },
            },
            y: {
                grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
                ticks: { font: { size: 9 }, color: '#8080a0' },
                border: { display: false },
                ...bounds,
            },
        },
    };
}

function createBarChart(canvasId, labels, data, unit, color) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const mn = Math.min(...data.filter(v => v != null));
    const opts = _baseOptions(data, unit);
    if (mn <= 20) opts.scales.y.suggestedMin = 0;

    new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: color + '40',
                borderColor: color,
                borderWidth: 1,
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: opts,
    });
}

function createLineChart(canvasId, labels, data, unit, color) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const chartCtx = ctx.getContext('2d');
    const h = ctx.parentElement ? ctx.parentElement.offsetHeight : 130;
    const gradient = chartCtx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, color + '30');
    gradient.addColorStop(1, color + '00');

    new Chart(chartCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                borderColor: color,
                backgroundColor: gradient,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointHoverBackgroundColor: color,
                pointHoverBorderColor: '#1e1e3f',
                pointHoverBorderWidth: 2,
                fill: true,
                tension: 0.4,
            }],
        },
        options: _baseOptions(data, unit),
    });
}

function createLineChartWithThreshold(canvasId, labels, data, unit, color, threshold, thresholdColor) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const chartCtx = ctx.getContext('2d');
    const h = ctx.parentElement ? ctx.parentElement.offsetHeight : 130;
    const gradient = chartCtx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, color + '30');
    gradient.addColorStop(1, color + '00');

    const allVals = [...data, threshold];
    const opts = _baseOptions(allVals, unit);
    opts.plugins.tooltip.filter = (item) => item.datasetIndex === 0;

    new Chart(chartCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    data: data,
                    borderColor: color,
                    backgroundColor: gradient,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: color,
                    pointHoverBorderColor: '#1e1e3f',
                    pointHoverBorderWidth: 2,
                    fill: true,
                    tension: 0.4,
                },
                {
                    data: Array(labels.length).fill(threshold),
                    borderColor: thresholdColor + '80',
                    borderWidth: 1,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: opts,
    });
}
