import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { hasSession, signIn, signOut } from "../api/auth";
import { setSessionLostHandler } from "../api/client";
import { getMe, putProfile } from "../api/endpoints";
import type { InvestorProfile, User } from "../api/types";

type Status = "loading" | "anon" | "authed";
type Ctx = {
  status: Status;
  user: User | null;
  login(username: string, password: string): Promise<User>;
  logout(): void;
  saveProfile(p: InvestorProfile): Promise<void>;
};

const C = createContext<Ctx>(null as never);
export const useApp = () => useContext(C);

export function AppProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(hasSession() ? "loading" : "anon");
  const [user, setUser] = useState<User | null>(null);

  const logout = useCallback(() => { signOut(); setUser(null); setStatus("anon"); }, []);

  useEffect(() => {
    setSessionLostHandler(logout);
    if (!hasSession()) return;
    getMe().then((u) => { setUser(u); setStatus("authed"); }).catch(() => logout());
  }, [logout]);

  const value = useMemo<Ctx>(() => ({
    status, user, logout,
    async login(username, password) {
      await signIn(username.trim(), password);
      let me: User;
      try {
        me = await getMe();
      } catch (e) {
        signOut();
        throw e;
      }
      setUser(me);
      setStatus("authed");
      return me;
    },
    async saveProfile(p) {
      setUser(await putProfile(p));
    },
  }), [status, user, logout]);

  return <C.Provider value={value}>{children}</C.Provider>;
}
