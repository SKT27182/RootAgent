/**
 * Authentication utilities for RootAgent frontend
 */

const AUTH_TOKEN_KEY = 'auth_token';
const USER_ID_KEY = 'user_id';
const USERNAME_KEY = 'username';

/**
 * Get the stored auth token
 * @returns {string|null} The JWT token or null if not authenticated
 */
function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY);
}

/**
 * Get the authenticated user's ID
 * @returns {string|null} The user ID or null if not authenticated
 */
function getUserId() {
    return localStorage.getItem(USER_ID_KEY);
}

/**
 * Get the authenticated user's username
 * @returns {string|null} The username or null if not authenticated
 */
function getUsername() {
    return localStorage.getItem(USERNAME_KEY);
}

/**
 * Check if user is authenticated
 * @returns {boolean} True if user has a valid auth token stored
 */
function isAuthenticated() {
    const token = getAuthToken();
    if (!token) return false;
    
    // Basic check - could add JWT expiry validation here
    try {
        // Decode JWT payload (base64)
        const payload = JSON.parse(atob(token.split('.')[1]));
        const expiry = payload.exp * 1000; // Convert to milliseconds
        return Date.now() < expiry;
    } catch (e) {
        return false;
    }
}

/**
 * Clear auth data and redirect to login
 */
function logout() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(USER_ID_KEY);
    localStorage.removeItem(USERNAME_KEY);
    window.location.href = 'login.html';
}

/**
 * Redirect to login if not authenticated
 * Call this on protected pages
 */
function requireAuth() {
    if (!isAuthenticated()) {
        logout();
    }
}

// Export for modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        getAuthToken,
        getUserId,
        getUsername,
        isAuthenticated,
        logout,
        requireAuth
    };
}
