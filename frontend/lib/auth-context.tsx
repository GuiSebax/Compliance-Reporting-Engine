"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const STORAGE_KEY = "cre_access_token";

interface AuthContextValue {
  token: string | null;
  isLoading: boolean;
  setToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Token only ever lives in this browser's localStorage — never sent
    // anywhere except as the Authorization header on API calls. This read
    // can only happen client-side post-mount (no localStorage during SSR),
    // so a one-time hydration effect is the correct tool here, not a
    // lint-rule violation to work around.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTokenState(window.localStorage.getItem(STORAGE_KEY));
    setIsLoading(false);
  }, []);

  const setToken = useCallback((next: string) => {
    window.localStorage.setItem(STORAGE_KEY, next);
    setTokenState(next);
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setTokenState(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, isLoading, setToken, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
