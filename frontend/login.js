// Use relative path since frontend and backend are served from same origin
const API_BASE_URL = '';

let isRegisterMode = false;

// DOM Elements
const authCard = document.getElementById('auth-card');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');
const authForm = document.getElementById('auth-form');
const submitBtn = document.getElementById('submit-btn');
const toggleText = document.getElementById('toggle-text');
const toggleLink = document.getElementById('toggle-link');
const errorMessage = document.getElementById('error-message');
const successMessage = document.getElementById('success-message');
const usernameInput = document.getElementById('username');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');

// Check if already logged in
document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('auth_token');
    if (token) {
        // Validate token
        validateToken(token).then(valid => {
            if (valid) {
                window.location.href = 'index.html';
            } else {
                localStorage.removeItem('auth_token');
                localStorage.removeItem('user_id');
                localStorage.removeItem('username');
            }
        });
    }
});

async function validateToken(token) {
    try {
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        return response.ok;
    } catch (e) {
        return false;
    }
}

function toggleMode() {
    isRegisterMode = !isRegisterMode;
    hideMessages();
    
    if (isRegisterMode) {
        authCard.classList.add('register-mode');
        authTitle.textContent = 'Create Account';
        authSubtitle.textContent = 'Sign up to get started with RootAgent';
        submitBtn.textContent = 'Create Account';
        toggleText.innerHTML = 'Already have an account? <a onclick="toggleMode()">Sign in</a>';
        emailInput.setAttribute('required', 'required');
    } else {
        authCard.classList.remove('register-mode');
        authTitle.textContent = 'Welcome Back';
        authSubtitle.textContent = 'Sign in to continue to RootAgent';
        submitBtn.textContent = 'Sign In';
        toggleText.innerHTML = 'Don\'t have an account? <a onclick="toggleMode()">Sign up</a>';
        emailInput.removeAttribute('required');
    }
    
    // Reset form
    authForm.reset();
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
    successMessage.style.display = 'none';
}

function showSuccess(message) {
    successMessage.textContent = message;
    successMessage.style.display = 'block';
    errorMessage.style.display = 'none';
}

function hideMessages() {
    errorMessage.style.display = 'none';
    successMessage.style.display = 'none';
}

authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideMessages();
    
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    const email = emailInput.value.trim();
    
    if (!username || !password) {
        showError('Please fill in all required fields');
        return;
    }
    
    if (isRegisterMode && !email) {
        showError('Please enter your email');
        return;
    }

    if (password.length < 6) {
        showError('Password must be at least 6 characters');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.textContent = isRegisterMode ? 'Creating...' : 'Signing in...';
    
    try {
        const endpoint = isRegisterMode ? '/auth/register' : '/auth/login';
        const body = isRegisterMode 
            ? { username, email, password }
            : { username, password };
        
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Authentication failed');
        }
        
        // Store auth data
        localStorage.setItem('auth_token', data.access_token);
        localStorage.setItem('user_id', data.user_id);
        localStorage.setItem('username', data.username);
        
        showSuccess(isRegisterMode ? 'Account created successfully!' : 'Login successful!');
        
        // Redirect to chat
        setTimeout(() => {
            window.location.href = 'index.html';
        }, 500);
        
    } catch (error) {
        console.error('Auth error:', error);
        showError(error.message || 'An error occurred. Please try again.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = isRegisterMode ? 'Create Account' : 'Sign In';
    }
});

// Make toggleMode globally accessible
window.toggleMode = toggleMode;
