import { useEffect, useState } from "react";
import { AbsenceReason, AuditStaffPeriod, PayPeriod, api } from "./api";

export function AuditPage() {
  const [periods, setPeriods] = useState<PayPeriod[]>([]);
  const [periodStart, setPeriodStart] = useState("");
  const [audit, setAudit] = useState<{
    clean: AuditStaffPeriod[];
    flagged: AuditStaffPeriod[];
    clean_count: number;
    flagged_count: number;
  } | null>(null);
  const [reasons, setReasons] = useState<AbsenceReason[]>([]);
  const [selected, setSelected] = useState<AuditStaffPeriod | null>(null);
  const [timesheet, setTimesheet] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [drawHours, setDrawHours] = useState("8");
  const [drawPreview, setDrawPreview] = useState<string | null>(null);

  const loadPeriods = async () => {
    const res = await api.listPayPeriods();
    setPeriods(res.periods);
    if (!periodStart && res.periods[0]) {
      setPeriodStart(res.periods[0].start_date);
    }
  };

  const loadAudit = async (start: string) => {
    if (!start) return;
    const res = await api.getPeriodAudit(start);
    setAudit(res);
  };

  useEffect(() => {
    loadPeriods().catch((e) => setError(e.message));
    api.listReasons().then((r) => setReasons(r.reasons)).catch(() => {});
  }, []);

  useEffect(() => {
    if (periodStart) {
      loadAudit(periodStart).catch((e) => setError(e.message));
    }
  }, [periodStart]);

  const openStaff = async (row: AuditStaffPeriod) => {
    setSelected(row);
    setDrawPreview(null);
    setSuccess(null);
    const ts = await api.getStaffTimesheet(periodStart, row.staff_id);
    setTimesheet(ts);
  };

  const onProposeDraw = async () => {
    if (!selected) return;
    const p = await api.proposePtoDraw(selected.staff_id, drawHours);
    setDrawPreview(`Draw ${p.hours}h → balance ${p.balance_before} → ${p.balance_after}`);
  };

  const onConfirmDraw = async (absenceId?: string, workDate?: string) => {
    if (!selected) return;
    try {
      await api.confirmPtoDraw({
        staff_id: selected.staff_id,
        hours: drawHours,
        pay_period_start: periodStart,
        work_date: workDate,
        absence_id: absenceId,
        confirmed: true,
      });
      setSuccess("PTO draw confirmed");
      await loadAudit(periodStart);
      if (selected) await openStaff(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Draw failed");
    }
  };

  const onAttachAbsence = async (workDate: string, reasonId: string) => {
    if (!selected) return;
    try {
      await api.upsertAbsence({
        staff_id: selected.staff_id,
        absence_date: workDate,
        reason_id: reasonId,
        pay_period_start: periodStart,
      });
      setSuccess(`Absence attached for ${workDate}`);
      await loadAudit(periodStart);
      await openStaff(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Absence failed");
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Biweekly audit</h2>
        <p>Review pay periods — clean vs flagged staff; resolve issues with reasons, PTO draws, and timesheet edits</p>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {success && <div className="success-banner">{success}</div>}

      <div className="card form-grid" style={{ gridTemplateColumns: "240px 1fr" }}>
        <div className="form-field">
          <label>Pay period</label>
          <select value={periodStart} onChange={(e) => setPeriodStart(e.target.value)}>
            {periods.map((p) => (
              <option key={p.start_date} value={p.start_date}>
                {p.start_date} – {p.end_date}
              </option>
            ))}
          </select>
        </div>
        {audit && (
          <p style={{ margin: 0, alignSelf: "end", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {audit.clean_count} clean · {audit.flagged_count} flagged
          </p>
        )}
      </div>

      {audit && (
        <>
          <div className="card audit-section audit-clean">
            <h3>Clean</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Wk 1 hrs</th>
                  <th>Wk 2 hrs</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {audit.clean.map((s) => (
                  <tr key={s.staff_id}>
                    <td className="mono">{s.staff_code}</td>
                    <td>
                      {s.display_name ?? `${s.first_name} ${s.last_name}`}
                    </td>
                    <td>{s.week1_hours}</td>
                    <td>{s.week2_hours}</td>
                    <td>
                      <button type="button" className="btn" onClick={() => openStaff(s)}>
                        Timesheet
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card audit-section audit-flagged">
            <h3>Flagged</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Wk 1</th>
                  <th>Wk 2</th>
                  <th>Flags</th>
                  <th>PTO bal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {audit.flagged.map((s) => (
                  <tr key={s.staff_id}>
                    <td className="mono">{s.staff_code}</td>
                    <td>
                      {s.display_name ?? `${s.first_name} ${s.last_name}`}
                    </td>
                    <td>{s.week1_hours}</td>
                    <td>{s.week2_hours}</td>
                    <td>
                      {s.flags.map((f) => (
                        <span key={`${f.work_date}-${f.flag_type}`} className="badge-warn" style={{ marginRight: 4 }}>
                          {f.flag_type}
                        </span>
                      ))}
                    </td>
                    <td>{s.pto_balance}</td>
                    <td>
                      <button type="button" className="btn btn-primary" onClick={() => openStaff(s)}>
                        Resolve
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected && (
        <div className="card">
          <h3>
            {selected.staff_code} — {selected.display_name ?? `${selected.first_name} ${selected.last_name}`}
          </h3>
          <ul style={{ fontSize: "0.9rem", color: "var(--text-secondary)" }}>
            {selected.flags.map((f) => (
              <li key={`${f.work_date}-${f.flag_type}`}>
                {f.work_date}: <strong>{f.flag_type}</strong> — {f.detail}
              </li>
            ))}
          </ul>

          <div className="form-grid" style={{ marginTop: "1rem" }}>
            <div className="form-field">
              <label>PTO draw hours (propose → confirm)</label>
              <input value={drawHours} onChange={(e) => setDrawHours(e.target.value)} />
            </div>
            <div className="form-actions" style={{ alignItems: "end" }}>
              <button type="button" className="btn" onClick={onProposeDraw}>
                Propose draw
              </button>
              <button type="button" className="btn btn-primary" onClick={() => onConfirmDraw()}>
                Confirm draw
              </button>
            </div>
          </div>
          {drawPreview && <p className="mono" style={{ color: "var(--accent-primary)" }}>{drawPreview}</p>}

          <h4 style={{ marginTop: "1.25rem" }}>Attach absence reason</h4>
          <div className="form-grid">
            {selected.flags
              .filter((f) => f.flag_type === "absence" || f.flag_type === "under_hours")
              .slice(0, 3)
              .map((f) => (
                <div key={f.work_date} className="form-field">
                  <label>{f.work_date}</label>
                  <select
                    defaultValue=""
                    onChange={(e) => {
                      if (e.target.value) onAttachAbsence(f.work_date, e.target.value);
                    }}
                  >
                    <option value="">— reason —</option>
                    {reasons.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name} ({r.funding})
                      </option>
                    ))}
                  </select>
                </div>
              ))}
          </div>

          {timesheet && (
            <pre
              style={{
                marginTop: "1rem",
                fontSize: "0.75rem",
                overflow: "auto",
                maxHeight: 200,
                background: "var(--surface-app)",
                padding: "0.75rem",
              }}
            >
              {JSON.stringify(timesheet, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
