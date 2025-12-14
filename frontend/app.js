// Auto-detect local dev (port 3000) vs Docker (nginx on port 80)
const isLocalDev = window.location.port === '3000';
const API_BASE_URL = isLocalDev ? 'http://localhost:8000/chat' : '/chat';

// Debug helper - logs to localStorage to persist across refreshes
function debugLog(message) {
    const logs = JSON.parse(localStorage.getItem('debug_logs') || '[]');
    logs.push(`[${new Date().toISOString()}] ${message}`);
    // Keep only last 50 entries
    if (logs.length > 50) logs.shift();
    localStorage.setItem('debug_logs', JSON.stringify(logs));
    console.log('[DEBUG]', message);
}

// Call this in console to see logs: showDebugLogs()
window.showDebugLogs = function() {
    const logs = JSON.parse(localStorage.getItem('debug_logs') || '[]');
    console.log('=== Debug Logs ===');
    logs.forEach(log => console.log(log));
};

window.clearDebugLogs = function() {
    localStorage.removeItem('debug_logs');
    console.log('Debug logs cleared');
};

debugLog('Script loaded');

// Capture when page is about to refresh/navigate
window.addEventListener('beforeunload', (e) => {
    debugLog('BEFOREUNLOAD triggered - page is navigating away!');
});

// Get authenticated user ID from auth.js
let USER_ID = getUserId();
debugLog(`Initial USER_ID: ${USER_ID}`);

// Note: Auth redirect handled in DOMContentLoaded to avoid race conditions

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
const reasoningToggle = document.getElementById('reasoning-toggle');
const backendReasoningToggle = document.getElementById('backend-reasoning-toggle');

// Stored Files
let attachedFiles = [];

// DOM Elements for auth
const userDisplay = document.getElementById('user-display');
const logoutBtn = document.getElementById('logout-btn');

// Init
document.addEventListener('DOMContentLoaded', () => {
    debugLog('DOMContentLoaded fired');
    
    // Check authentication
    if (!isAuthenticated()) {
        debugLog('Auth check failed in DOMContentLoaded - redirecting to login');
        window.location.href = 'login.html';
        return;
    }
    debugLog('Auth check passed');
    
    // Update USER_ID from auth
    USER_ID = getUserId();
    
    // Display username
    if (userDisplay && getUsername()) {
        userDisplay.textContent = getUsername();
    }
    
    loadSessions();
    setupTheme();
    setupEventListeners();
});

function setupEventListeners() {
    newChatBtn.addEventListener('click', startNewChat);
    
    sendBtn.addEventListener('click', sendMessage);
    
    // Logout handler
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
    
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
    debugLog('loadSessions called');
    try {
        const res = await fetch(`${API_BASE_URL}/sessions/${USER_ID}`);
        if (!res.ok) throw new Error('Failed to load sessions');
        const sessions = await res.json();
        debugLog(`loadSessions got ${sessions.length} sessions`);
        renderHistoryList(sessions);
    } catch (err) {
        debugLog(`loadSessions error: ${err.message}`);
        console.error(err);
    }
}

function renderHistoryList(sessions) {
    historyList.innerHTML = '';
    sessions.forEach(sessionId => {
        const div = document.createElement('div');
        div.className = `history-item ${sessionId === currentSessionId ? 'active' : ''}`;
        
        const sessionText = document.createElement('span');
        sessionText.className = 'session-text';
        sessionText.textContent = sessionId.substring(0, 8) + '...'; // Show truncated ID
        sessionText.title = sessionId; // Full ID on hover
        sessionText.onclick = () => loadChatHistory(sessionId);
        
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'session-actions';
        
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button'; // Prevent form submission
        copyBtn.className = 'session-action-btn copy-btn';
        copyBtn.innerHTML = '<span class="material-icons-round">content_copy</span>';
        copyBtn.title = 'Copy session ID';
        copyBtn.onclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            navigator.clipboard.writeText(sessionId);
            copyBtn.innerHTML = '<span class="material-icons-round">check</span>';
            setTimeout(() => {
                copyBtn.innerHTML = '<span class="material-icons-round">content_copy</span>';
            }, 1500);
        };
        
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button'; // Prevent form submission
        deleteBtn.className = 'session-action-btn delete-btn';
        deleteBtn.innerHTML = '<span class="material-icons-round">delete</span>';
        deleteBtn.title = 'Delete session';
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            deleteSession(sessionId);
        };
        
        actionsDiv.appendChild(copyBtn);
        actionsDiv.appendChild(deleteBtn);
        div.appendChild(sessionText);
        div.appendChild(actionsDiv);
        historyList.appendChild(div);
    });
}

async function deleteSession(sessionId) {
    if (!confirm('Delete this session? This cannot be undone.')) return;
    
    try {
        const res = await fetch(`${API_BASE_URL}/sessions/${USER_ID}/${sessionId}`, {
            method: 'DELETE'
        });
        
        if (!res.ok) throw new Error('Failed to delete session');
        
        // If we deleted the current session, start a new chat
        if (sessionId === currentSessionId) {
            startNewChat();
        }
        
        // Reload session list
        loadSessions();
    } catch (err) {
        console.error('Delete error:', err);
        alert('Failed to delete session');
    }
}

async function startNewChat() {
    debugLog('startNewChat called');
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
    // Handle local dev vs Docker
    if (isLocalDev) {
        return `ws://localhost:8000/chat/ws`;
    }
    // Construct WebSocket URL from current host
    return `${proto}//${window.location.host}/chat/ws`;
}

async function sendMessage() {
    debugLog('sendMessage called');
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
    const showReasoning = reasoningToggle ? reasoningToggle.checked : true;
    const backendReasoning = backendReasoningToggle ? backendReasoningToggle.checked : true;
    const payload = {
        query: text || "Processed uploaded files.", 
        user_id: USER_ID,
        session_id: currentSessionId,
        include_reasoning: backendReasoning,
        images: [],
        csv_data: null
    };

    // Process Files (Async)
    try {
        for (const file of attachedFiles) {
            console.log(`Processing file: ${file.name}, type: ${file.type}`);
            if (file.type.startsWith('image/')) {
                payload.images.push(await toBase64(file));
            } else if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
                const content = await readTextFile(file);
                console.log(`CSV content length: ${content.length}`);
                if (payload.csv_data) payload.csv_data += '\n' + content; 
                else payload.csv_data = content;
            } else {
                const content = await readTextFile(file);
                payload.query += `\n\n[File: ${file.name}]\n${content}`;
            }
        }
    } catch (fileError) {
        console.error('Error processing files:', fileError);
        appendMessage('bot', `Error processing file(s): ${fileError.message}`, false);
        sendBtn.disabled = false;
        return;
    }

    // Clear files
    attachedFiles = [];
    renderFilePreviews();

    // Branch based on show reasoning toggle (controls UI streaming vs HTTP)
    if (showReasoning) {
        // Use WebSocket for streaming with reasoning
        sendMessageStreaming(payload);
    } else {
        // Use HTTP for non-streaming without reasoning
        sendMessageHttp(payload);
    }
}

async function sendMessageHttp(payload) {
    // Create Bot Message Container (simple, no reasoning)
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    
    const finalBubble = document.createElement('div');
    finalBubble.className = 'message-bubble';
    finalBubble.innerHTML = '<span class="loading-dots">Thinking...</span>';
    msgDiv.appendChild(finalBubble);
    
    chatContainer.appendChild(msgDiv);
    scrollToBottom();

    try {
        const response = await fetch(API_BASE_URL + '/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const data = await response.json();
        finalBubble.innerHTML = formatBotResponse(data.response);
        
        // Update session ID if new
        if (data.session_id && !currentSessionId) {
            currentSessionId = data.session_id;
            loadSessions();
        }
    } catch (error) {
        console.error('HTTP request error:', error);
        finalBubble.innerHTML = `<span class="error-text">Error: ${error.message}</span>`;
    } finally {
        sendBtn.disabled = false;
        scrollToBottom();
    }
}

function sendMessageStreaming(payload) {
    // WebSocket Connection
    const wsUrl = getWebSocketUrl();
    const ws = new WebSocket(wsUrl);
    
    // Create Bot Message Container
    const msgDiv = document.createElement('div');
    msgDiv.className = `message bot`;
    
    // 1. Reasoning Block (for streaming tokens)
    const reasoningBubble = document.createElement('div');
    reasoningBubble.className = 'reasoning-block';
    reasoningBubble.style.display = 'block';
    reasoningBubble.innerHTML = '<div class="reasoning-header">Reasoning</div>';
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
                if (window.currentReasoningStepProp.div) {
                    try {
                        window.currentReasoningStepProp.div.innerHTML = marked.parse(window.currentReasoningStepProp.content);
                    } catch(e) {
                        console.error('Marked parse error:', e);
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
                // Display error in the reasoning block
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
                debugLog(`WS info received: session_id=${data.session_id}`);
                if (data.session_id) {
                    currentSessionId = data.session_id;
                    debugLog('Calling loadSessions after info');
                    loadSessions();
                }
                break;
        }
    };

    ws.onclose = () => {
        sendBtn.disabled = false;
        if (finalBubble.style.display === 'none' && currentReasoning) {
             // Just leave reasoning as is.
        }
    };

    ws.onerror = (error) => {
        console.error("WebSocket Error:", error);
        console.error("WebSocket readyState:", ws.readyState);
        // Don't append a new message if we've already shown something
        if (finalBubble.style.display === 'none' && !window.currentReasoningStepProp.content) {
            appendMessage('bot', "Connection error. Please try again.", false);
        }
        sendBtn.disabled = false;
    };
}

function appendMessage(role, content, isReasoning) {
    // Debug: Log the raw content being processed
    console.log('[appendMessage] role:', role, 'isReasoning:', isReasoning);
    console.log('[appendMessage] raw content (first 200 chars):', content?.substring(0, 200));
    
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    
    const bubble = document.createElement('div');
    if (isReasoning) {
        bubble.className = 'reasoning-block';
        // Render reasoning content as markdown for proper code block display
        const reasoningContent = parseContent(content);
        console.log('[appendMessage] parsed reasoning (first 200 chars):', reasoningContent?.substring(0, 200));
        const renderedContent = formatBotResponse(reasoningContent);
        console.log('[appendMessage] rendered HTML (first 200 chars):', renderedContent?.substring(0, 200));
        bubble.innerHTML = `<div class="reasoning-header">Reasoning</div><div class="reasoning-step">${renderedContent}</div>`;
    } else {
        bubble.className = 'message-bubble';
        const parsedContext = parseContent(content);
        console.log('[appendMessage] parsed content (first 200 chars):', parsedContext?.substring(0, 200));
        // Render bot responses as markdown, escape user messages
        bubble.innerHTML = role === 'user' ? escapeHtml(parsedContext) : formatBotResponse(parsedContext);
    }
    
    msgDiv.appendChild(bubble);
    chatContainer.appendChild(msgDiv);
}

// Helpers
function handleFileSelect(e) {
    debugLog(`handleFileSelect called with ${e.target.files.length} files`);
    const files = Array.from(e.target.files);
    attachedFiles = [...attachedFiles, ...files];
    debugLog(`Total attached files: ${attachedFiles.length}`);
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
    // Check if the text is a base64 image (PNG/JPEG)
    if (isBase64Image(text)) {
        return renderBase64Image(text);
    }
    
    // Render markdown using marked.js
    try {
        return marked.parse(text);
    } catch (e) {
        console.error('Markdown parsing error:', e);
        return escapeHtml(text);
    }
}

function isBase64Image(text) {
    if (typeof text !== 'string') return false;
    
    // Trim whitespace
    const trimmed = text.trim();
    
    // Check if it's a data URL with image
    if (trimmed.startsWith('data:image/')) {
        return true;
    }
    
    // Check if it looks like a raw base64 PNG (starts with PNG magic bytes in base64)
    // PNG base64 starts with "iVBORw0KGgo"
    if (trimmed.startsWith('iVBORw0KGgo')) {
        return true;
    }
    
    // Check for JPEG (starts with "/9j/")
    if (trimmed.startsWith('/9j/')) {
        return true;
    }
    
    // Additional check: if it's a long alphanumeric string without spaces/newlines, might be base64
    // Only if it's reasonably long (images are typically large)
    if (trimmed.length > 100 && /^[A-Za-z0-9+/=]+$/.test(trimmed)) {
        return true;
    }
    
    return false;
}

function renderBase64Image(text) {
    const trimmed = text.trim();
    let dataUrl;
    
    if (trimmed.startsWith('data:image/')) {
        // Already a data URL
        dataUrl = trimmed;
    } else if (trimmed.startsWith('iVBORw0KGgo')) {
        // PNG
        dataUrl = `data:image/png;base64,${trimmed}`;
    } else if (trimmed.startsWith('/9j/')) {
        // JPEG
        dataUrl = `data:image/jpeg;base64,${trimmed}`;
    } else {
        // Default to PNG
        dataUrl = `data:image/png;base64,${trimmed}`;
    }
    
    return `
        <div class="image-response">
            <img src="${dataUrl}" alt="Generated Chart" class="generated-image" onclick="openImageFullscreen(this)">
            <button class="download-btn" onclick="downloadImage('${dataUrl}', 'chart.png')">
                <span class="material-icons-round">download</span> Download
            </button>
        </div>
    `;
}

// Download image helper
window.downloadImage = function(dataUrl, filename) {
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = filename;
    link.click();
};

// Fullscreen image viewer
window.openImageFullscreen = function(img) {
    const overlay = document.createElement('div');
    overlay.className = 'image-overlay';
    overlay.innerHTML = `
        <img src="${img.src}" alt="Fullscreen Image">
        <button class="close-overlay" onclick="this.parentElement.remove()">
            <span class="material-icons-round">close</span>
        </button>
    `;
    overlay.onclick = (e) => {
        if (e.target === overlay) overlay.remove();
    };
    document.body.appendChild(overlay);
};

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
