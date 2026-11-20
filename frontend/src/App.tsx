import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useApp } from "./lib/store";
import AssetPage from "./pages/AssetPage";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Explore from "./pages/Explore";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Markets from "./pages/Markets";
import Portfolio from "./pages/Portfolio";
import Profile from "./pages/Profile";
import Register from "./pages/Register";

export function Private({ children }: { children: ReactNode }) {
  const { status } = useApp();
  if (status === "loading") return <p className="muted" style={{ padding: 48 }}>Chargement…</p>;
  return status === "authed" ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/inscription" element={<Register />} />
      <Route path="/explorer" element={<Explore />} />
      <Route path="/accueil" element={<Private><Dashboard /></Private>} />
      <Route path="/chat" element={<Private><Chat /></Private>} />
      <Route path="/portefeuille" element={<Private><Portfolio /></Private>} />
      <Route path="/marches" element={<Private><Markets /></Private>} />
      <Route path="/marches/:ticker" element={<Private><AssetPage /></Private>} />
      <Route path="/profil" element={<Private><Profile /></Private>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
