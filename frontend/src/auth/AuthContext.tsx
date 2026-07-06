import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "../api/client";

type User = { id: number; username: string } | null;
type Ctx = {
  user: User; loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  register: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
};
const AuthCtx = createContext<Ctx>(null!);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);
  const login = async (u: string, p: string) => { await api.login(u, p); setUser(await api.me()); };
  const register = async (u: string, p: string) => { await api.register(u, p); await login(u, p); };
  const logout = async () => { await api.logout(); setUser(null); };
  return <AuthCtx.Provider value={{ user, loading, login, register, logout }}>{children}</AuthCtx.Provider>;
}
