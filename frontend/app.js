const API_BASE_URL = 'http://localhost:8000/chat';
const USER_ID = 'user_' + Math.random().toString(36).substr(2, 9); // Simple random user ID for demo

// State
let currentSessionId = null;
let isDark = true;

// DOM Elements
const historyList = document.getElementById('history-list');
const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const fileUpload = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const filePreviews = document.getElementById('file-previews');
const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');

// Stored Files
let attachedFiles = [];

// Init
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    setupTheme();
    setupEventListeners();
});

function setupEventListeners() {
    newChatBtn.addEventListener('click', startNewChat);
    
    sendBtn.addEventListener('click', sendMessage);
    
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
        adjustTextareaHeight();
    });
    
    userInput.addEventListener('input', () => {
        sendBtn.disabled = !userInput.value.trim() && attachedFiles.length === 0;
        adjustTextareaHeight();
    });

    uploadBtn.addEventListener('click', () => fileUpload.click());
    
    fileUpload.addEventListener('change', handleFileSelect);
    
    themeToggle.addEventListener('click', toggleTheme);
}

// Session Management
async function loadSessions() {
    try {
        const res = await fetch(`${API_BASE_URL}/sessions/${USER_ID}`);
        if (!res.ok) throw new Error('Failed to load sessions');
        const sessions = await res.json();
        renderHistoryList(sessions);
    } catch (err) {
        console.error(err);
    }
}

function renderHistoryList(sessions) {
    historyList.innerHTML = '';
    sessions.forEach(sessionId => {
        const div = document.createElement('div');
        div.className = `history-item ${sessionId === currentSessionId ? 'active' : ''}`;
        div.textContent = sessionId; // In real app, maybe show summary or date
        div.onclick = () => loadChatHistory(sessionId);
        historyList.appendChild(div);
    });
}

async function startNewChat() {
    currentSessionId = null;
    chatContainer.innerHTML = `
        <div class="welcome-message" id="welcome-message">
            <h1>How can I help you today?</h1>
        </div>
    `;
    updateActiveSessionInList(null);
}

async function loadChatHistory(sessionId) {
    currentSessionId = sessionId;
    updateActiveSessionInList(sessionId);
    
    chatContainer.innerHTML = ''; // Clear current
    
    try {
        const res = await fetch(`${API_BASE_URL}/history/${USER_ID}/${sessionId}?include_reasoning=true`);
        if (!res.ok) throw new Error('Failed to load history');
        const messages = await res.json();
        
        messages.forEach(msg => {
            appendMessage(msg.role, msg.content, msg.is_reasoning);
        });
        scrollToBottom();
    } catch (err) {
        console.error(err);
    }
}

function updateActiveSessionInList(sessionId) {
    const items = historyList.querySelectorAll('.history-item');
    items.forEach(item => {
        if (item.textContent === sessionId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

// Messaging
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text && attachedFiles.length === 0) return;

    // UI Updates
    userInput.value = '';
    sendBtn.disabled = true;
    userInput.style.height = 'auto'; // Reset height
    
    // Clear welcome message if present
    const welcome = document.getElementById('welcome-message');
    if (welcome) welcome.remove();

    // Show User Message
    appendMessage('user', text + (attachedFiles.length ? ` [${attachedFiles.length} file(s)]` : ''), false);
    scrollToBottom();

    // Prepare Payload
    const payload = {
        query: text || "Processed uploaded files.", // Fallback if only files
        user_id: USER_ID,
        session_id: currentSessionId,
        include_reasoning: true,
        images: [],
        csv_data: null
    };

    // Process Files
    for (const file of attachedFiles) {
        if (file.type.startsWith('image/')) {
            payload.images.push(await toBase64(file));
        } else if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
            // Only support one CSV for now as per simple backend
             const content = await readTextFile(file);
             if (payload.csv_data) payload.csv_data += '\n' + content; // Append if multiple?
             else payload.csv_data = content;
        } else {
             // Treat as text?
             const content = await readTextFile(file);
             payload.query += `\n\n[File: ${file.name}]\n${content}`;
        }
    }

    // Clear files
    attachedFiles = [];
    renderFilePreviews();

    // Send to Backend
    try {
        const res = await fetch(`${API_BASE_URL}/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errorData = await res.json();
            throw new Error(errorData.detail || 'Error sending message');
        }

        const data = await res.json();
        
        // If it was a new session, update ID and list
        if (!currentSessionId) {
            currentSessionId = data.session_id;
            loadSessions(); // Refresh list to show new session
        }

        // The backend returns the FINAL response.
        // However, we asked for reasoning. But the backend *response* model only has `response`.
        // The *history* has reasoning.
        // Wait, the endpoints logic: `generated_steps` are saved to redis.
        // But `chat_endpoint` returns `ChatResponse` which ONLY has `response` text.
        // Effectively, we won't see reasoning in the immediate response unless we fetch history or update backend to return it.
        // For this minimal implementation, I will just display the final response.
        // If we want reasoning, we'd need to fetch history again or stream. 
        // Let's just fetch the latest history to get reasoning, or just show final response.
        
        // Better UX: Show final response. If we really want reasoning "live", we need streaming or different response structure.
        // I will just show the final response for now as per "minimal" requirement request, 
        // BUT the prompt said "show reasoning in little reasoning block". 
        // Since I can't get it from the immediate response, I will fetch history immediately after to get the latest messages.
        
        await loadChatHistory(currentSessionId); 

    } catch (err) {
        appendMessage('bot', `Error: ${err.message}`, false);
    } finally {
        scrollToBottom();
    }
}

function appendMessage(role, content, isReasoning) {
    // If reasoning, check if we already have it? 
    // Since we reload history, we might duplicate if not careful.
    // simpler to just clear and reload or unique check. 
    // loadChatHistory clears all, so it's safe.
    
    // But for the user message "echo", we append it manually. 
    // When we reload history, it will be there. 
    
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    
    const bubble = document.createElement('div');
    if (isReasoning) {
        bubble.className = 'reasoning-block';
        bubble.innerHTML = `<div class="reasoning-header">Reasoning</div>${escapeHtml(content)}`;
    } else {
        bubble.className = 'message-bubble';
        const parsedContext = parseContent(content);
        // Handle basic markdown? For minimal, just text with newlines
        bubble.innerHTML = role === 'user' ? escapeHtml(parsedContext) : formatBotResponse(parsedContext);
    }
    
    msgDiv.appendChild(bubble);
    chatContainer.appendChild(msgDiv);
}

// Helpers
function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    attachedFiles = [...attachedFiles, ...files];
    renderFilePreviews();
    sendBtn.disabled = false;
    fileUpload.value = ''; // Reset
}

function renderFilePreviews() {
    filePreviews.innerHTML = '';
    attachedFiles.forEach((file, index) => {
        const pill = document.createElement('div');
        pill.className = 'file-pill';
        pill.innerHTML = `
            <span class="material-icons-round" style="font-size: 16px;">description</span>
            ${file.name}
            <span class="material-icons-round remove-file" style="font-size: 16px;" onclick="removeFile(${index})">close</span>
        `;
        filePreviews.appendChild(pill);
    });
}

window.removeFile = (index) => {
    attachedFiles.splice(index, 1);
    renderFilePreviews();
    if (attachedFiles.length === 0 && !userInput.value.trim()) {
        sendBtn.disabled = true;
    }
};

function adjustTextareaHeight() {
    userInput.style.height = 'auto';
    userInput.style.height = userInput.scrollHeight + 'px';
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function toggleTheme() {
    isDark = !isDark;
    document.body.className = isDark ? 'dark-mode' : 'light-mode';
    themeIcon.textContent = isDark ? 'light_mode' : 'dark_mode';
}

function setupTheme() {
    // Check local storage or system pref? Default Dark.
    if (!isDark) {
        toggleTheme(); // Switch to light if default was light
    }
}

function escapeHtml(text) {
    if (typeof text !== 'string') return text;
    return text.replace(/&/g, "&amp;")
               .replace(/</g, "&lt;")
               .replace(/>/g, "&gt;")
               .replace(/"/g, "&quot;")
               .replace(/'/g, "&#039;")
               .replace(/\n/g, '<br>');
}

function formatBotResponse(text) {
    // Simple formatter
    return escapeHtml(text);
}

// File Utils
function toBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => {
            // Remove prefix "data:image/png;base64,"
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = error => reject(error);
    });
}

function readTextFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsText(file);
        reader.onload = () => resolve(reader.result);
        reader.onerror = error => reject(error);
    });
}

function parseContent(content) {
    try {
        const parsed = JSON.parse(content);
        if (Array.isArray(parsed)) {
            return parsed.map(item => {
                if (item.type === 'text') return item.text;
                if (item.type === 'image_url') return '[Image]';
                return JSON.stringify(item);
            }).join('');
        }
        return content;
    } catch (e) {
        return content;
    }
}
