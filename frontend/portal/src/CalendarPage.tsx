import { FormEvent, useEffect, useMemo, useState } from "react";
import { AbsenceReason, CalendarAbsence, Staff, api } from "./api";

function monthBounds(year: number, month: number) {
  const start = new Date(year, month, 1);
  const end = new Date(year, month + 1, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    start_date: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-01`,
    end_date: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`,
    daysInMonth: end.getDate(),
    firstWeekday: start.getDay(),
  };
}

export function CalendarPage() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [staff, setStaff] = useState<Staff[]>([]);
  const [reasons, setReasons] = useState<AbsenceReason[]>([]);
  const [absences, setAbsences] = useState<CalendarAbsence[]>([]);
  const [shortStaffed, setShortStaffed] = useState<{ work_date: string; absent_count: number; staff_codes: string[] }[]>([]);
  const [selectedStaffId, setSelectedStaffId] = useState("");
  const [upcoming, setUpcoming] = useState<CalendarAbsence[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [formDate, setFormDate] = useState("");
  const [formStaffId, setFormStaffId] = useState("");
  const [formReasonId, setFormReasonId] = useState("");
  const [formNotes, setFormNotes] = useState("");

  const bounds = useMemo(() => monthBounds(year, month), [year, month]);

  const load = async () => {
    const [cal, staffRes, reasonRes] = await Promise.all([
      api.getCalendarAbsences(bounds.start_date, bounds.end_date),
      api.listStaff(),
      api.listReasons(),
    ]);
    setAbsences(cal.absences);
    setShortStaffed(cal.short_staffed_days);
    setStaff(staffRes.staff.filter((s) => s.is_active));
    setReasons(reasonRes.reasons);
  };

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : "Load failed"));
  }, [year, month]);

  useEffect(() => {
    if (!selectedStaffId) {
      setUpcoming([]);
      return;
    }
    api
      .getUpcomingAbsences(selectedStaffId)
      .then((r) => setUpcoming(r.upcoming))
      .catch(() => setUpcoming([]));
  }, [selectedStaffId, absences]);

  const absencesByDate = useMemo(() => {
    const m = new Map<string, CalendarAbsence[]>();
    for (const a of absences) {
      const list = m.get(a.absence_date) ?? [];
      list.push(a);
      m.set(a.absence_date, list);
    }
    return m;
  }, [absences]);

  const shortSet = useMemo(() => new Set(shortStaffed.map((d) => d.work_date)), [shortStaffed]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.upsertAbsence({
        staff_id: formStaffId,
        absence_date: formDate,
        reason_id: formReasonId,
        notes: formNotes || undefined,
      });
      setSuccess(`Planned absence saved for ${formDate}`);
      setShowForm(false);
      await load();
      if (formStaffId) setSelectedStaffId(formStaffId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const cells: React.ReactNode[] = [];
  for (let i = 0; i < bounds.firstWeekday; i++) {
    cells.push(<td key={`pad-${i}`} className="calendar-cell calendar-pad" />);
  }
  for (let day = 1; day <= bounds.daysInMonth; day++) {
    const pad = (n: number) => String(n).padStart(2, "0");
    const iso = `${year}-${pad(month + 1)}-${pad(day)}`;
    const dayAbs = absencesByDate.get(iso) ?? [];
    const isShort = shortSet.has(iso);
    cells.push(
      <td
        key={iso}
        className={`calendar-cell${isShort ? " calendar-short" : ""}${dayAbs.length ? " calendar-has-absence" : ""}`}
        onClick={() => {
          setFormDate(iso);
          setShowForm(true);
        }}
      >
        <div className="calendar-day-num">{day}</div>
        {dayAbs.map((a) => (
          <div key={a.id} className="calendar-absence-chip" title={a.reason_name}>
            {a.staff_code}
          </div>
        ))}
        {isShort && <div className="calendar-short-label">Short</div>}
      </td>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h2>Planned absences</h2>
        <p>Calendar of vacations and planned time off — future-dated entry with short-staffed-day visibility</p>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {success && <div className="success-banner">{success}</div>}

      <div className="form-actions" style={{ marginBottom: "1rem" }}>
        <button type="button" className="btn" onClick={() => setMonth((m) => (m === 0 ? (setYear((y) => y - 1), 11) : m - 1))}>
          ← Prev
        </button>
        <span style={{ color: "var(--text-secondary)" }}>
          {year}-{String(month + 1).padStart(2, "0")}
        </span>
        <button type="button" className="btn" onClick={() => setMonth((m) => (m === 11 ? (setYear((y) => y + 1), 0) : m + 1))}>
          Next →
        </button>
        <button type="button" className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Cancel" : "Add planned absence"}
        </button>
      </div>

      {showForm && (
        <form className="card" onSubmit={onSubmit}>
          <h3>Future / planned absence</h3>
          <div className="form-grid">
            <div className="form-field">
              <label>Date</label>
              <input type="date" value={formDate} onChange={(e) => setFormDate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Staff</label>
              <select value={formStaffId} onChange={(e) => setFormStaffId(e.target.value)} required>
                <option value="">— select —</option>
                {staff.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.staff_code} — {s.first_name} {s.last_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>Reason</label>
              <select value={formReasonId} onChange={(e) => setFormReasonId(e.target.value)} required>
                <option value="">— select —</option>
                {reasons.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>Notes</label>
              <input value={formNotes} onChange={(e) => setFormNotes(e.target.value)} />
            </div>
          </div>
          <button type="submit" className="btn btn-primary">
            Save
          </button>
        </form>
      )}

      <div className="card">
        <table className="data-table calendar-grid">
          <thead>
            <tr>
              {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
                <th key={d}>{d}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: Math.ceil((bounds.firstWeekday + bounds.daysInMonth) / 7) }, (_, row) => (
              <tr key={row}>{cells.slice(row * 7, row * 7 + 7)}</tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Short-staffed days</h3>
        {shortStaffed.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>No short-staffed days this month.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Absent</th>
                <th>Staff codes</th>
              </tr>
            </thead>
            <tbody>
              {shortStaffed.map((d) => (
                <tr key={d.work_date}>
                  <td>{d.work_date}</td>
                  <td>{d.absent_count}</td>
                  <td className="mono">{d.staff_codes.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Staff upcoming absences</h3>
        <select
          value={selectedStaffId}
          onChange={(e) => setSelectedStaffId(e.target.value)}
          style={{ marginBottom: "0.75rem" }}
        >
          <option value="">— select staff —</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.staff_code}
            </option>
          ))}
        </select>
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Reason</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((u) => (
              <tr key={u.id}>
                <td>{u.absence_date}</td>
                <td>{u.reason_name}</td>
                <td>{u.notes ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
