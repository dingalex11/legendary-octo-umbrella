const pdfDropZone = document.getElementById('pdf-drop-zone');
const pdfFileInput = document.getElementById('pdf-file-input');
const pdfOutputJSON = document.getElementById('pdf-output-json');
const pdfStatusText = document.getElementById('pdf-status-text');
const pdfLoader = document.getElementById('pdf-loader');
const pdfDownloadBtn = document.getElementById('btn-download-json');
const pdfCopyBtn = document.getElementById('btn-copy-json');
const pdfCountBadge = document.getElementById('pdf-count-badge');

let currentParsedData = null;
let currentPdfFileName = "parsed_bank";

if(pdfDropZone) {
    pdfDropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        pdfDropZone.classList.add('dragover');
    });

    pdfDropZone.addEventListener('dragleave', () => {
        pdfDropZone.classList.remove('dragover');
    });

    pdfDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        pdfDropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            handlePDFFile(e.dataTransfer.files[0]);
        }
    });
}

if(pdfFileInput) {
    pdfFileInput.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handlePDFFile(e.target.files[0]);
        }
    });
}

async function handlePDFFile(file) {
    if (file.type !== 'application/pdf') {
        alert("Please provide a valid PDF file.");
        return;
    }

    currentPdfFileName = file.name.replace('.pdf', '');
    setPDFLoadingState(true);

    try {
        const arrayBuffer = await file.arrayBuffer();
        const rawText = await extractCleanText(arrayBuffer);
        const parsedQuestions = parseScienceBowlText(rawText);
        
        currentParsedData = parsedQuestions;
        
        pdfOutputJSON.textContent = JSON.stringify(parsedQuestions, null, 2);
        pdfStatusText.innerText = "EXTRACTION COMPLETE";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-teamA font-bold";
        
        pdfCountBadge.style.display = "block";
        pdfCountBadge.innerText = `${parsedQuestions.length} SETS EXTRACTED`;
        pdfCountBadge.className = "bg-teal-950 text-teamA border border-teal-800 px-2 py-1 rounded text-xs font-mono font-bold";

        pdfDownloadBtn.disabled = false;
        pdfCopyBtn.disabled = false;

    } catch (err) {
        console.error(err);
        pdfStatusText.innerText = "ERROR PARSING PDF";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-red-500 font-bold";
        pdfOutputJSON.textContent = "// Error: " + err.message;
    } finally {
        setPDFLoadingState(false);
    }
}

function setPDFLoadingState(isLoading) {
    if (isLoading) {
        pdfLoader.style.display = 'block';
        pdfDropZone.style.pointerEvents = 'none';
        
        pdfDropZone.querySelectorAll('span:not(#pdf-loader), b').forEach(el => el.style.opacity = '0');
        
        pdfStatusText.innerText = "PROCESSING PDF DATA...";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-amber-500 font-bold";
        pdfOutputJSON.textContent = "// Extracting text...";
    } else {
        pdfLoader.style.display = 'none';
        pdfDropZone.style.pointerEvents = 'auto';
        
        pdfDropZone.querySelectorAll('span:not(#pdf-loader), b').forEach(el => el.style.opacity = '1');
    }
}

async function extractCleanText(arrayBuffer) {
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    let fullText = "";

    for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const content = await page.getTextContent();
        const pageText = content.items.map(item => item.str).join(" ");
        fullText += pageText + "\n";
    }

    fullText = fullText.replace(/\r\n|\r/g, "\n");
    fullText = fullText.replace(/(?:High|Middle)\s+School\s+Round\s+\d+\s+Page\s+\d+/gi, "");
    fullText = fullText.replace(/Page\s+\d+/gi, "");
    fullText = fullText.replace(/\(read as:.*?\)/gi, "");

    return fullText;
}

function parseScienceBowlText(rawText) {
    const questions = [];
    const blockPattern = /(?:TOSSUP|TOSS-UP|BONUS)\s*\d*[\.\)]?\s*(?:([A-Za-z\s]+?)\s*[,:]?\s*)?(Short Answer|Multiple Choice|MULTIPLE CHOICE|SHORT ANSWER)\s+(.*?)ANSWER:\s*(.*?)(?=(?:TOSSUP|TOSS-UP|BONUS|$))/gsi;
    const matches = [...rawText.matchAll(blockPattern)];
    let currentSet = null;

    for (const match of matches) {
        let categoryRaw = match[1] ? match[1].trim() : "General Science";
        let typeRaw = match[2] ? match[2].trim() : "Short Answer";
        let bodyRaw = match[3] ? match[3] : "";
        let answerRaw = match[4] ? match[4] : "";

        let categoryClean = titleCase(categoryRaw);
        let qTypeClean = titleCase(typeRaw);
        let qBodyClean = bodyRaw.replace(/\s+/g, " ").trim();
        let answerClean = answerRaw.replace(/\s+/g, " ").trim();
        
        let typeCode = qTypeClean.toLowerCase().includes("multiple") ? "MC" : "SA";

        answerClean = answerClean.replace(/\[[A-Z0-9\s]+\]$/i, "").trim();
        answerClean = answerClean.replace(/\s*(?:High|Middle)?\s*School\s*Round.*$/i, "").trim();
        answerClean = answerClean.replace(/\s*Page\s*\d+.*$/i, "").trim();

        let formattedQuestion = `${categoryClean}. ${qTypeClean}. ${qBodyClean}`;

        if (currentSet === null) {
            currentSet = {
                category: categoryClean,
                type: typeCode,
                tossup_text: formattedQuestion,
                tossup_answer: answerClean,
                bonus_text: "",
                bonus_answer: ""
            };
        } else {
            currentSet.bonus_text = formattedQuestion;
            currentSet.bonus_answer = answerClean;
            questions.push(currentSet);
            currentSet = null;
        }
    }

    if (currentSet !== null) {
        questions.push(currentSet);
    }

    return questions;
}

function titleCase(str) {
    return str.toLowerCase().split(' ').map(function(word) {
        return (word.charAt(0).toUpperCase() + word.slice(1));
    }).join(' ');
}

function downloadJSON() {
    if (!currentParsedData) return;
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentParsedData, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", `${currentPdfFileName}_bank.json`);
    document.body.appendChild(downloadAnchorNode); 
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
}

function copyJSON() {
    if (!currentParsedData) return;
    navigator.clipboard.writeText(JSON.stringify(currentParsedData, null, 2))
        .then(() => {
            const originalText = pdfCopyBtn.innerText;
            pdfCopyBtn.innerText = "Copied!";
            pdfCopyBtn.classList.add("text-teamA", "border-teamA");
            setTimeout(() => {
                pdfCopyBtn.innerText = originalText;
                pdfCopyBtn.classList.remove("text-teamA", "border-teamA");
            }, 2000);
        })
        .catch(err => {
            const textArea = document.createElement("textarea");
            textArea.value = JSON.stringify(currentParsedData, null, 2);
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand("copy");
            textArea.remove();
            pdfCopyBtn.innerText = "Copied!";
            setTimeout(() => pdfCopyBtn.innerText = "Copy to Clipboard", 2000);
        });
}