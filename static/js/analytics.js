const csvDropZone = document.getElementById('csv-drop-zone');
const csvFileInput = document.getElementById('csv-file-input');
const teamStatsBody = document.getElementById('team-stats-body');
const playerStatsBody = document.getElementById('player-stats-body');
const csvStatusText = document.getElementById('csv-status-text');
const csvCountBadge = document.getElementById('csv-count-badge');

let globalTeamStats = {};
let globalPlayerStats = {};
let gamesProcessed = new Set();

if(csvDropZone) {
    csvDropZone.addEventListener('dragover', (e) => { e.preventDefault(); csvDropZone.classList.add('dragover'); });
    csvDropZone.addEventListener('dragleave', () => { csvDropZone.classList.remove('dragover'); });
    csvDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        csvDropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleCSVFiles(e.dataTransfer.files);
    });
}

if(csvFileInput) {
    csvFileInput.addEventListener('change', (e) => {
        if (e.target.files.length) handleCSVFiles(e.target.files);
    });
}

function resetAnalytics() {
    globalTeamStats = {};
    globalPlayerStats = {};
    gamesProcessed.clear();
    if(teamStatsBody) teamStatsBody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-600">Awaiting data...</td></tr>';
    if(playerStatsBody) playerStatsBody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-600">Awaiting data...</td></tr>';
    if(csvCountBadge) csvCountBadge.style.display = "none";
    if(csvStatusText) {
        csvStatusText.innerText = "SYSTEM READY // WAITING FOR MATCH CSV";
        csvStatusText.className = "text-xs font-mono mt-1 block uppercase text-slate-400";
    }
}

async function handleCSVFiles(files) {
    csvStatusText.innerText = "PROCESSING CSV DATA...";
    csvStatusText.className = "text-xs font-mono mt-1 block uppercase text-amber-500 font-bold";

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!file.name.endsWith('.csv')) continue;
        
        const text = await file.text();
        processCSVData(text, file.name);
    }

    renderAnalyticsTables();
    
    csvCountBadge.style.display = "block";
    csvCountBadge.innerText = `${gamesProcessed.size} GAMES PROCESSED`;
    csvStatusText.innerText = "ANALYTICS COMPILED SUCCESSFULLY";
    csvStatusText.className = "text-xs font-mono mt-1 block uppercase text-teamA font-bold";
}

function processCSVData(csvText, fileName) {
    gamesProcessed.add(fileName);
    const lines = csvText.trim().split('\n');
    const headers = lines[0].split(',').map(h => h.trim());
    
    lines.slice(1).forEach(line => {
        const values = line.split(',');
        let row = {};
        headers.forEach((h, i) => row[h] = values[i] ? values[i].trim() : '');

        const eventType = row['Event_Type'];
        const team = row['Team'];
        const player = row['Player'];
        if (!team || !eventType) return;

        const points = parseInt(row['Points']) || 0;
        const isCorrect = row['Correct'] === 'True';
        const buzzTime = parseFloat(row['Buzz_Time']) || 0.0;
        const buzzpoint = row['Buzzpoint'] || "";

        if (!globalTeamStats[team]) {
            globalTeamStats[team] = { games: new Set(), total_points: 0, tossup_points: 0, bonus_points: 0, correct: 0, negs: 0, interrupts: 0 };
        }
        globalTeamStats[team].games.add(fileName);
        globalTeamStats[team].total_points += points;

        if (eventType === 'TOSSUP' || eventType === 'TOSSUP_REBOUND') {
            globalTeamStats[team].tossup_points += points;
            if (isCorrect) globalTeamStats[team].correct += 1;
            if (points === -4) { globalTeamStats[team].negs += 1; globalTeamStats[team].interrupts += 1; }
        } else if (eventType === 'BONUS') {
            globalTeamStats[team].bonus_points += points;
        }

        if (player && (eventType === 'TOSSUP' || eventType === 'TOSSUP_REBOUND')) {
            const pKey = `${team} - ${player}`;
            if (!globalPlayerStats[pKey]) {
                globalPlayerStats[pKey] = { team: team, games: new Set(), buzzes: 0, points: 0, correct: 0, negs: 0, int_attempts: 0, int_correct: 0, total_speed: 0.0 };
            }
            
            let p = globalPlayerStats[pKey];
            p.games.add(fileName);
            p.buzzes += 1;
            p.points += points;
            if (buzzTime > 0) p.total_speed += buzzTime;

            const isInterrupt = (buzzpoint.toLowerCase() !== "full read" && buzzpoint !== "") || points === -4;
            
            if (isCorrect) p.correct += 1;
            if (points === -4) p.negs += 1;

            if (isInterrupt) {
                p.int_attempts += 1;
                if (isCorrect) p.int_correct += 1;
            }
        }
    });
}

function renderAnalyticsTables() {
    if(teamStatsBody) teamStatsBody.innerHTML = "";
    const sortedTeams = Object.entries(globalTeamStats).sort((a, b) => (b[1].total_points / b[1].games.size) - (a[1].total_points / a[1].games.size));
    
    sortedTeams.forEach(([team, data]) => {
        const gp = data.games.size;
        const ppg = (data.total_points / gp).toFixed(2);
        const ppb = data.correct > 0 ? (data.bonus_points / data.correct).toFixed(2) : "0.00";

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="py-2 px-3 font-bold">${team}</td>
            <td class="py-2 px-3">${gp}</td>
            <td class="py-2 px-3">${data.total_points}</td>
            <td class="py-2 px-3 text-teamA">${ppg}</td>
            <td class="py-2 px-3 text-purple-300 font-bold">${ppb}</td>
            <td class="py-2 px-3">${data.correct}</td>
            <td class="py-2 px-3 text-red-400">${data.negs}</td>
        `;
        if(teamStatsBody) teamStatsBody.appendChild(tr);
    });

    if(playerStatsBody) playerStatsBody.innerHTML = "";
    const sortedPlayers = Object.entries(globalPlayerStats).sort((a, b) => b[1].points - a[1].points);

    sortedPlayers.forEach(([pKey, p]) => {
        const gp = p.games.size;
        const ppg = (p.points / gp).toFixed(2);
        const ppa = p.buzzes > 0 ? (p.points / p.buzzes).toFixed(2) : "0.00";
        const intRate = p.buzzes > 0 ? ((p.int_attempts / p.buzzes) * 100).toFixed(1) : "0.0";
        const intAcc = p.int_attempts > 0 ? ((p.int_correct / p.int_attempts) * 100).toFixed(1) : "0.0";
        const avgSpd = p.buzzes > 0 && p.total_speed > 0 ? (p.total_speed / p.buzzes).toFixed(3) : "N/A";

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="py-2 px-3 font-bold">
                <span class="block">${pKey.split('-')[1].trim()}</span>
                <span class="text-[9px] text-slate-500">${p.team}</span>
            </td>
            <td class="py-2 px-3">${p.points}</td>
            <td class="py-2 px-3">${ppg}</td>
            <td class="py-2 px-3 text-amber-300 font-bold">${ppa}</td>
            <td class="py-2 px-3 ${intAcc > 50 ? 'text-teamA' : 'text-slate-400'}">${intAcc}%</td>
            <td class="py-2 px-3 text-red-400">${intRate}%</td>
            <td class="py-2 px-3 text-cyan-400">${avgSpd}</td>
        `;
        if(playerStatsBody) playerStatsBody.appendChild(tr);
    });
}