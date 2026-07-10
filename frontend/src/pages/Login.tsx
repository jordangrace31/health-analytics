import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try { await login(u, p); nav("/"); } catch { setErr("Invalid credentials"); }
  };
  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: "4rem auto", display: "grid", gap: 12 }}>
      <h1>Log in</h1>
      <label>Username<input value={u} onChange={e => setU(e.target.value)} /></label>
      <label>Password<input type="password" value={p} onChange={e => setP(e.target.value)} /></label>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      <button type="submit">Log in</button>
      <p>No account? <Link to="/register">Register</Link></p>
    </form>
  );
}
