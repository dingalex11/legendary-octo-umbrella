// /static/js/auth.js

import { initializeApp } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-app.js";
import { 
    getAuth, 
    signInWithEmailAndPassword, 
    createUserWithEmailAndPassword, 
    signOut, 
    onAuthStateChanged 
} from "https://www.gstatic.com/firebasejs/12.0.0/firebase-auth.js";
import { 
    getFirestore, 
    doc, 
    setDoc, 
    getDoc,
    collection, 
    addDoc, 
    getDocs
} from "https://www.gstatic.com/firebasejs/12.0.0/firebase-firestore.js";

// Your Firebase project configuration
const firebaseConfig = {
  apiKey: "AIzaSyBWoq9NNYIejMv6D8JM_oP0g_SGdH_ykJc",
  authDomain: "slopbowl-fe316.firebaseapp.com",
  projectId: "slopbowl-fe316",
  storageBucket: "slopbowl-fe316.firebasestorage.app",
  messagingSenderId: "73153730852",
  appId: "1:73153730852:web:e5eccfdc8fd8b4a6e23bb1",
  measurementId: "G-LLKJL520M9"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);

// DOM Elements
const authModal = document.getElementById('auth-modal');
const emailInput = document.getElementById('auth-email');
const passwordInput = document.getElementById('auth-password');
const btnSignIn = document.getElementById('btn-sign-in');
const btnSignUp = document.getElementById('btn-sign-up');
const authError = document.getElementById('auth-error');

const userSection = document.getElementById('auth-user-section');
const userEmailDisplay = document.getElementById('auth-user-email');
const btnShowLogin = document.getElementById('btn-show-login');
const btnSignOut = document.getElementById('btn-sign-out');

const settingsApiKeyInput = document.getElementById('settings-api-key');
const btnSaveSettings = document.getElementById('btn-save-settings');
const settingsStatus = document.getElementById('settings-status');

// --- CONSOLIDATED AUTHENTICATION STATE OBSERVER ---
onAuthStateChanged(auth, async (user) => {
    const cloudPacketSection = document.getElementById('cloud-packet-section');
    const btnSaveCloud = document.getElementById('btn-save-cloud');
    const btnCloudAnalytics = document.getElementById('btn-cloud-analytics');

    if (user) {
        // 1. Update Core Header UI
        userSection.classList.remove('hidden');
        userSection.classList.add('flex');
        btnShowLogin.classList.add('hidden');
        userEmailDisplay.innerText = user.email;
        authModal.classList.add('hidden'); 
        
        // 2. Reveal Cloud Feature Buttons
        if (cloudPacketSection) {
            cloudPacketSection.classList.remove('hidden');
            cloudPacketSection.classList.add('flex');
        }
        if (btnSaveCloud) btnSaveCloud.classList.remove('hidden');
        if (btnCloudAnalytics) btnCloudAnalytics.classList.remove('hidden');
        
        // 3. Fetch User Data (API Key & Cloud Packets)
        const docRef = doc(db, "users", user.uid);
        const docSnap = await getDoc(docRef);
        if (docSnap.exists() && docSnap.data().groqApiKey) {
            settingsApiKeyInput.value = docSnap.data().groqApiKey;
        }
        await window.populateCloudPackets();

    } else {
        // 1. Reset Core Header UI
        userSection.classList.remove('flex');
        userSection.classList.add('hidden');
        btnShowLogin.classList.remove('hidden');
        userEmailDisplay.innerText = "";
        settingsApiKeyInput.value = "";

        // 2. Hide Cloud Feature Buttons
        if (cloudPacketSection) {
            cloudPacketSection.classList.add('hidden');
            cloudPacketSection.classList.remove('flex');
        }
        if (btnSaveCloud) btnSaveCloud.classList.add('hidden');
        if (btnCloudAnalytics) btnCloudAnalytics.classList.add('hidden');
    }
});

// --- UI EVENT LISTENERS ---
const displayError = (msg) => {
    authError.innerText = msg;
    authError.classList.remove('hidden');
};

btnSignIn?.addEventListener('click', async () => {
    try {
        authError.classList.add('hidden');
        await signInWithEmailAndPassword(auth, emailInput.value, passwordInput.value);
    } catch (error) {
        displayError(error.message);
    }
});

btnSignUp?.addEventListener('click', async () => {
    try {
        authError.classList.add('hidden');
        await createUserWithEmailAndPassword(auth, emailInput.value, passwordInput.value);
    } catch (error) {
        displayError(error.message);
    }
});

btnSignOut?.addEventListener('click', async () => {
    try {
        await signOut(auth);
    } catch (error) {
        console.error("Error signing out: ", error);
    }
});

// --- USER SETTINGS (API KEY) ---
btnSaveSettings?.addEventListener('click', async () => {
    const user = auth.currentUser;
    if (!user) {
        settingsStatus.innerText = "⚠️ You must be logged in to save settings.";
        settingsStatus.className = "text-xs text-red-400 bg-red-950/50 border border-red-900 p-2 rounded font-mono block";
        return;
    }

    const apiKey = settingsApiKeyInput.value.trim();
    try {
        settingsStatus.innerText = "Saving...";
        settingsStatus.className = "text-xs text-amber-400 bg-amber-950/50 border border-amber-900 p-2 rounded font-mono block";
        
        await setDoc(doc(db, "users", user.uid), {
            groqApiKey: apiKey,
            updatedAt: new Date().toISOString()
        }, { merge: true });

        settingsStatus.innerText = "✅ API Key saved securely to your cloud profile!";
        settingsStatus.className = "text-xs text-emerald-400 bg-emerald-950/50 border border-emerald-900 p-2 rounded font-mono block";
        
        setTimeout(() => {
            settingsStatus.classList.add('hidden');
            document.getElementById('settings-modal').classList.add('hidden');
        }, 2000);
    } catch (error) {
        settingsStatus.innerText = `❌ Error: ${error.message}`;
        settingsStatus.className = "text-xs text-red-400 bg-red-950/50 border border-red-900 p-2 rounded font-mono block";
    }
});

// --- GLOBAL EXPORTS FOR OTHER SCRIPTS ---

window.getUserApiKey = async () => {
    const user = auth.currentUser;
    if (user) {
        const docRef = doc(db, "users", user.uid);
        const docSnap = await getDoc(docRef);
        if (docSnap.exists() && docSnap.data().groqApiKey) {
            return docSnap.data().groqApiKey;
        }
    }
    return null; 
};

window.savePacketToCloud = async (packetName, packetData) => {
    const user = auth.currentUser;
    if (!user) throw new Error("You must be logged in to save to the cloud.");

    const packetsRef = collection(db, "users", user.uid, "packets");
    await addDoc(packetsRef, {
        name: packetName,
        data: packetData,
        createdAt: new Date().toISOString()
    });
};

window.populateCloudPackets = async () => {
    const user = auth.currentUser;
    const select = document.getElementById('cloud-packet-select');
    if (!user || !select) return;

    select.innerHTML = '<option value="">Fetching...</option>';
    
    try {
        const packetsRef = collection(db, "users", user.uid, "packets");
        const querySnapshot = await getDocs(packetsRef);
        
        select.innerHTML = '<option value="">-- Select a Cloud Packet --</option>';
        window.cloudPacketsCache = {}; 
        
        querySnapshot.forEach((doc) => {
            const data = doc.data();
            window.cloudPacketsCache[doc.id] = data.data; 
            
            const option = document.createElement('option');
            option.value = doc.id;
            option.text = `${data.name} (${data.data.length} Qs)`;
            select.appendChild(option);
        });
    } catch (err) {
        select.innerHTML = '<option value="">Error loading packets</option>';
        console.error("Failed to load cloud packets:", err);
    }
};

window.saveMatchLogToCloud = async (roomId, logData) => {
    const user = auth.currentUser;
    if (!user || !roomId) return;
    
    try {
        const logRef = doc(db, "users", user.uid, "match_logs", roomId);
        await setDoc(logRef, {
            roomId: roomId,
            log: logData,
            updatedAt: new Date().toISOString()
        }, { merge: true }); 
    } catch (err) {
        console.error("Failed to sync match log to cloud:", err);
    }
};

window.loadMatchLogsFromCloud = async () => {
    const user = auth.currentUser;
    if (!user) throw new Error("You must be logged in to fetch cloud analytics.");
    
    const logsRef = collection(db, "users", user.uid, "match_logs");
    const snapshot = await getDocs(logsRef);
    
    const logs = [];
    snapshot.forEach(doc => logs.push(doc.data()));
    return logs;
};