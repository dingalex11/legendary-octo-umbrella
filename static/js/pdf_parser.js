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

// --- DRAG & DROP EVENT LISTENERS ---
if (pdfDropZone) {
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

if (pdfFileInput) {
    pdfFileInput.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handlePDFFile(e.target.files[0]);
        }
    });
}

// --- LIVE INLINE EDITOR SETUP ---
if (pdfOutputJSON) {
    // Make the pre block editable
    pdfOutputJSON.setAttribute('contenteditable', 'true');
    pdfOutputJSON.addEventListener('input', validateLiveJSON);
}

function validateLiveJSON() {
    try {
        // Attempt to parse the user's manual edits
        const parsed = JSON.parse(pdfOutputJSON.innerText);
        currentParsedData = parsed; 
        
        // Success UI State
        pdfOutputJSON.classList.remove('border-red-500', 'text-red-400');
        pdfStatusText.innerText = "EXTRACTION COMPLETE (VALID JSON)";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-teamA font-bold";
        pdfDownloadBtn.disabled = false;
        pdfCopyBtn.disabled = false;
    } catch (err) {
        // Error UI State
        pdfOutputJSON.classList.add('border-red-500', 'text-red-400');
        pdfStatusText.innerText = "⚠️ INVALID JSON SYNTAX";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-red-500 font-bold animate-pulse";
        pdfDownloadBtn.disabled = true;
        pdfCopyBtn.disabled = true;
    }
}

// --- MAIN PDF HANDLER ---
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
        
        // Pretty print to the editable output block
        pdfOutputJSON.innerText = JSON.stringify(parsedQuestions, null, 2);
        
        // Trigger the validation success state
        validateLiveJSON();
        
        pdfCountBadge.style.display = "block";
        pdfCountBadge.innerText = `${parsedQuestions.length} SETS EXTRACTED`;
        pdfCountBadge.className = "bg-teal-950 text-teamA border border-teal-800 px-2 py-1 rounded text-xs font-mono font-bold";

    } catch (err) {
        console.error(err);
        pdfStatusText.innerText = "ERROR PARSING PDF";
        pdfStatusText.className = "text-xs font-mono mt-1 block uppercase text-red-500 font-bold";
        pdfOutputJSON.innerText = "// Error: " + err.message;
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
        pdfOutputJSON.innerText = "// Extracting text...";
    } else {
        pdfLoader.style.display = 'none';
        pdfDropZone.style.pointerEvents = 'auto';
        pdfDropZone.querySelectorAll('span:not(#pdf-loader), b').forEach(el => el.style.opacity = '1');
    }
}

// --- PHASE 1: DYNAMIC SANITIZATION ---
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
    
    // Wipe out repeating line dividers (e.g. ~~~~ or ----)
    fullText = fullText.replace(/[~_-]{5,}/g, "");
    
    // Wipe out known footers based on tournament styles
    fullText = fullText.replace(/Page\s+\d+/gi, "");
    fullText = fullText.replace(/(?:High|Middle)\s+School\s+Round\s+\d+/gi, "");
    fullText = fullText.replace(/STANFORD SCIENCE BOWL/gi, "");
    fullText = fullText.replace(/\d{4}\s+MHS/gi, "");
    fullText = fullText.replace(/MIT Science Bowl Invitational Round \d+/gi, "");

    return fullText;
}

// --- PHASE 2 & 3: TOKENIZATION AND STATE MACHINE ---
function parseScienceBowlText(rawText) {
    // Split the document into question chunks via positive lookahead
    const chunkRegex = /(?=TOSSUP|TOSS-UP|BONUS|VISUAL BONUS)/gi;
    const chunks = rawText.split(chunkRegex).map(c => c.trim()).filter(c => c.length > 20);

    const questions = [];
    let currentSet = null;

    for (let chunk of chunks) {
        const isBonus = /^(?:VISUAL )?BONUS/i.test(chunk);
        const isVisual = /^VISUAL/i.test(chunk);
        const isTossup = /^TOSS-?UP/i.test(chunk);

        if (!isBonus && !isTossup) continue;

        // Extract the Answer block
        const answerSplit = chunk.split(/ANSWER:/i);
        if (answerSplit.length < 2) continue;

        let bodyAndMeta = answerSplit[0];
        let rawAnswer = answerSplit[1].replace(/\s+/g, " ").trim();

        // Extract Metadata (Category and Type)
        // FIX: Added Life Science, Physical Science, and General Science to the regex
        const metaMatch = bodyAndMeta.match(/(Biology|Chemistry|Physics|Math|Earth and Space|Earth Science|Energy|Life Science|Physical Science|General Science)[\s–-]*([^ \n]+ (?:Choice|Answer))/i);
        
        let category = "General Science";
        let type = "SA";

        if (metaMatch) {
            category = titleCase(metaMatch[1].trim());
            type = metaMatch[2].toLowerCase().includes("multiple") ? "MC" : "SA";
        } else if (bodyAndMeta.toLowerCase().includes("multiple choice")) {
            type = "MC";
        }

        // Clean up the body by removing structural headers
        // FIX: Match the updated categories here so they are cleanly stripped from the spoken text
        let cleanBody = bodyAndMeta
            .replace(/^(?:VISUAL )?(?:TOSS-?UP|BONUS)\s*\d*[\.\)]?/i, "")
            .replace(/(Biology|Chemistry|Physics|Math|Earth and Space|Earth Science|Energy|Life Science|Physical Science|General Science)[\s–-]+(?:Multiple Choice|Short Answer)/i, "")
            .replace(/\s+/g, " ")
            .trim();

        // Phase 4: Extract W, X, Y, Z for Multiple Choice
        let options = [];
        if (type === "MC") {
            // Looks for the specific W) X) Y) Z) patterns
            const optionsMatch = cleanBody.match(/(W\).*?)(X\).*?)(Y\).*?)(Z\).*)$/i);
            if (optionsMatch) {
                options = [
                    optionsMatch[1].trim(),
                    optionsMatch[2].trim(),
                    optionsMatch[3].trim(),
                    optionsMatch[4].trim()
                ];
                // Remove the options from the main text body so the TTS reader doesn't read them improperly
                cleanBody = cleanBody.replace(/(W\).*?)(X\).*?)(Y\).*?)(Z\).*)$/i, "").trim();
            }
        }

        let formattedQuestion = `${category}. ${type === 'MC' ? 'Multiple Choice' : 'Short Answer'}. ${cleanBody}`;

        // Package the Question Object
        if (isTossup || !currentSet) {
            currentSet = {
                category: category,
                type: type,
                tossup_text: formattedQuestion,
                tossup_answer: rawAnswer,
                tossup_options: options,
                tossup_visual: isVisual,
                bonus_text: "",
                bonus_answer: "",
                bonus_options: [],
                bonus_visual: false
            };
        } else if (isBonus && currentSet) {
            currentSet.bonus_text = formattedQuestion;
            currentSet.bonus_answer = rawAnswer;
            currentSet.bonus_options = options;
            currentSet.bonus_visual = isVisual;
            questions.push(currentSet);
            
            // Reset for the next Tossup/Bonus pair
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

// --- EXPORT UTILITIES ---
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