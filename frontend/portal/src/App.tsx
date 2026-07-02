import { FormEvent, useState } from "react";
import { ApiError, api, clearToken, getToken, setToken } from "./api";
import { ReportPage } from "./ReportPage";
import { CalendarPage } from "./CalendarPage";
import { AuditPage } from "./AuditPage";
import { AbsenceReasonsPage } from "./AbsenceReasonsPage";
import { PtoLadderPage } from "./PtoLadderPage";
import { SchedulesPage } from "./SchedulesPage";
import { StaffPage } from "./StaffPage";

type Page = "staff" | "schedules" | "reasons" | "pto-ladder" | "audit" | "calendar" | "report";

function Login({ onLogin }: { onLogin: () => void }) {
  const [token, setTokenInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setToken(token.trim());
    try {
      await api.listStaff();
      onLogin();
    } catch (err) {
      clearToken();
      if (err instanceof ApiError) {
        setError(err.status === 503 ? "Portal auth not configured on server" : "Invalid token");
      } else {
        setError("Connection failed");
      }
    }
  };

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <h1>RG Time</h1>
        <p className="subtitle">Admin Portal</p>
        {error && <div className="error-banner">{error}</div>}
        <label style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Admin API token</label>
        <input
          type="password"
          value={token}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="PORTAL_ADMIN_TOKEN"
          required
        />
        <button type="submit" className="btn btn-primary" style={{ width: "100%" }}>
          Sign in
        </button>
      </form>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [page, setPage] = useState<Page>("staff");

  const logout = () => {
    clearToken();
    setAuthed(false);
  };

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />;
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand">
          <h1>RG Time</h1>
          <p>Admin Portal</p>
        </div>
        <nav>
          <button type="button" className={page === "staff" ? "active" : ""} onClick={() => setPage("staff")}>
            Staff
          </button>
          <button type="button" className={page === "schedules" ? "active" : ""} onClick={() => setPage("schedules")}>
            Schedules
          </button>
          <button type="button" className={page === "reasons" ? "active" : ""} onClick={() => setPage("reasons")}>
            Absence reasons
          </button>
          <button type="button" className={page === "pto-ladder" ? "active" : ""} onClick={() => setPage("pto-ladder")}>
            PTO Ladder
          </button>
          <button type="button" className={page === "audit" ? "active" : ""} onClick={() => setPage("audit")}>
            Biweekly audit
          </button>
          <button type="button" className={page === "calendar" ? "active" : ""} onClick={() => setPage("calendar")}>
            Calendar
          </button>
          <button type="button" className={page === "report" ? "active" : ""} onClick={() => setPage("report")}>
            Reports
          </button>
          <button type="button" onClick={logout} style={{ marginTop: "2rem", color: "var(--text-muted)" }}>
            Sign out
          </button>
        </nav>
      </aside>
      <main className="main-content">
        {page === "staff" && <StaffPage />}
        {page === "schedules" && <SchedulesPage />}
        {page === "reasons" && <AbsenceReasonsPage />}
        {page === "pto-ladder" && <PtoLadderPage />}
        {page === "audit" && <AuditPage />}
        {page === "calendar" && <CalendarPage />}
        {page === "report" && <ReportPage />}
      </main>
    </div>
  );
}
