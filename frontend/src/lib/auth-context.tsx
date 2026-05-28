import React, { createContext, useContext, useState, useEffect } from "react";
import { api, getMe, type AuthUser } from "../api";

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  login: (token: string, user?: AuthUser | null) => void;
  logout: () => void;
  loadUser: () => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));

  useEffect(() => {
    if (token) {
      api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      if (!user) {
        getMe()
          .then((res) => setUser(res.data))
          .catch(() => logout());
      }
    } else {
      delete api.defaults.headers.common["Authorization"];
    }
  }, [token]);

  const login = (newToken: string, newUser: AuthUser | null = null) => {
    localStorage.setItem("token", newToken);
    setToken(newToken);
    if (newUser) {
      setUser(newUser);
    }
  };

  const logout = () => {
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
  };

  const loadUser = async () => {
    const res = await getMe();
    setUser(res.data);
  };

  return (
    <AuthContext.Provider
      value={{ user, token, login, logout, loadUser, isAuthenticated: !!token }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
