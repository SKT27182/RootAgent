const API_BASE_URL = 'http://localhost:8000/chat';
const USER_ID = 'user_' + Math.random().toString(36).substr(2, 9); // Simple random user ID for demo

// Configure Marked.js with Highlight.js and Custom Renderer
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true
});

const renderer = new marked.Renderer();
renderer.code = function(tokenOrCode, language) {
    let code = tokenOrCode;
    let lang = language;

    // Handle marked newer versions passing token object
    if (typeof tokenOrCode === 'object' && tokenOrCode !== null) {
        code = tokenOrCode.text || '';
        lang = tokenOrCode.lang || '';
    }

    try {
        // Safe check for hljs
        if (typeof hljs === 'undefined') {
            console.warn('Highlight.js not loaded');
            return `<div class="code-wrapper"><pre><code>${code}</code></pre></div>`;
        }

        const validLang = !!(language && hljs.getLanguage(language));
        const highlighted = validLang 
            ? hljs.highlight(code, { language: language }).value 
            : hljs.highlightAuto(code).value;
            
        return `<div class="code-wrapper">
            <div class="code-header">
                <span class="code-lang">${language || 'code'}</span>
                <button class="copy-btn" onclick="copyToClipboard(this)">
                    <span class="material-icons-round">content_copy</span> Copy
                </button>
            </div>
            <pre><code class="hljs ${language || ''}">${highlighted}</code></pre>
        </div>`;
    } catch (e) {
        console.error('Highlighting error:', e);
         // Fallback to plain text
        return `<div class="code-wrapper">
             <div class="code-header"><span class="code-lang">text</span></div>
             <pre><code>${code}</code></pre>
        </div>`;
    }
};
marked.use({ renderer });

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
// Messaging
function getWebSocketUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Assuming API is on localhost:8000 provided by API_BASE_URL which is http://localhost:8000/chat
    // We want ws://localhost:8000/chat/ws
    return API_BASE_URL.replace('http:', 'ws:').replace('https:', 'wss:') + '/ws';
}

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text && attachedFiles.length === 0) return;

    // UI Updates
    // Clear input
    userInput.value = '';
    // Reset file uploads
    fileUpload.value = '';
    filePreviews.innerHTML = '';
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
        query: text || "Processed uploaded files.", 
        user_id: USER_ID,
        session_id: currentSessionId,
        include_reasoning: true,
        images: [],
        csv_data: null
    };

    // Process Files (Async)
    for (const file of attachedFiles) {
        if (file.type.startsWith('image/')) {
            payload.images.push(await toBase64(file));
        } else if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
             const content = await readTextFile(file);
             if (payload.csv_data) payload.csv_data += '\n' + content; 
             else payload.csv_data = content;
        } else {
             const content = await readTextFile(file);
             payload.query += `\n\n[File: ${file.name}]\n${content}`;
        }
    }

    // Clear files
    attachedFiles = [];
    renderFilePreviews();

    // WebSocket Connection
    const wsUrl = getWebSocketUrl();
    const ws = new WebSocket(wsUrl);
    
    // Create Bot Message Container
    const msgDiv = document.createElement('div');
    msgDiv.className = `message bot`;
    
    // 1. Reasoning Block (for streaming tokens)
    const reasoningBubble = document.createElement('div');
    reasoningBubble.className = 'reasoning-block';
    reasoningBubble.style.display = 'block'; // Ensure visible
    reasoningBubble.innerHTML = '<div class="reasoning-header">Reasoning</div>'; // Header first
    msgDiv.appendChild(reasoningBubble);
    
    // Reset current text node global for new message
    window.currentReasoningStepProp = {
        div: null,
        content: ""
    };

    // Create first step container
    const createStepContainer = () => {
        const div = document.createElement('div');
        div.className = 'reasoning-step';
        reasoningBubble.appendChild(div);
        return div;
    };
    window.currentReasoningStepProp.div = createStepContainer();

    
    // 2. Final Answer Bubble (initially empty/hidden until final)
    const finalBubble = document.createElement('div');
    finalBubble.className = 'message-bubble';
    finalBubble.style.display = 'none';
    msgDiv.appendChild(finalBubble);
    
    chatContainer.appendChild(msgDiv);
    
    let currentReasoning = "";

    ws.onopen = () => {
        ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
            case 'token':
                // Append token to current step content
                window.currentReasoningStepProp.content += data.content;
                // Render markdown for current step
                // Render markdown for current step
                if (window.currentReasoningStepProp.div) {
                    try {
                        window.currentReasoningStepProp.div.innerHTML = marked.parse(window.currentReasoningStepProp.content);
                    } catch(e) {
                        console.error('Marked parse error:', e);
                        // Fallback to text
                        window.currentReasoningStepProp.div.textContent = window.currentReasoningStepProp.content;
                    }
                }
                scrollToBottom();
                break;
                
            case 'tool_output':
                // User requested to hide observation/tool outputs from reasoning
                break;
                
            case 'step_separator':
                // Visual separation for loops
                const hr = document.createElement('hr');
                hr.className = 'reasoning-separator';
                reasoningBubble.appendChild(hr);
                
                // Start new step container
                window.currentReasoningStepProp.div = createStepContainer();
                window.currentReasoningStepProp.content = "";
                scrollToBottom();
                break;
                
            case 'final':
                // Final answer received
                const finalContent = data.content;
                finalBubble.innerHTML = formatBotResponse(finalContent);
                finalBubble.style.display = 'block';
                scrollToBottom();
                ws.close();
                break;
                
            case 'error':
                // Display error in the reasoning block, not as a separate message
                window.currentReasoningStepProp.content += `\n\n**Error:** ${data.content}\n`;
                if (window.currentReasoningStepProp.div) {
                    try {
                        window.currentReasoningStepProp.div.innerHTML = marked.parse(window.currentReasoningStepProp.content);
                    } catch(e) {
                        window.currentReasoningStepProp.div.textContent = window.currentReasoningStepProp.content;
                    }
                }
                scrollToBottom();
                break;
            
            case 'info':
                if (data.session_id) {
                    currentSessionId = data.session_id;
                    loadSessions();
                }
                break;
        }
    };

    ws.onclose = () => {
        sendBtn.disabled = false;
        // If no final answer was shown (stream cut off?), maybe show what we have in reasoning?
        if (finalBubble.style.display === 'none' && currentReasoning) {
             // Just leave reasoning as is.
        }
    };

    ws.onerror = (error) => {
        console.error("WebSocket Error:", error);
        appendMessage('bot', "Connection error.", false);
        sendBtn.disabled = false;
    };
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

// Global Copy Function for code blocks
window.copyToClipboard = function(btn) {
    const wrapper = btn.closest('.code-wrapper');
    const code = wrapper.querySelector('code').innerText;
    
    navigator.clipboard.writeText(code).then(() => {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="material-icons-round">check</span> Copied!';
        setTimeout(() => {
            btn.innerHTML = originalHtml;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
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
