import { useEffect, useState } from "react";
import { PayPeriod, PayPeriodReport, Staff, api, getToken } from "./api";
import { TimeCardView } from "./TimeCardView";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function ReportPage() {
  const [periods, setPeriods] = useState<PayPeriod[]>([]);
  const [periodStart, setPeriodStart] = useState("");
  const [report, setReport] = useState<PayPeriodReport | null>(null);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [selectedStaffId, setSelectedStaffId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPayPeriods().then((r) => {
      setPeriods(r.periods);
      if (r.periods[0]) setPeriodStart(r.periods[0].start_date);
    });
    api.listStaff().then((r) => setStaff(r.staff.filter((s) => s.is_active)));
  }, []);

  useEffect(() => {
    if (!periodStart) return;
    api
      .getPayPeriodReport(periodStart)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed"));
  }, [periodStart]);

  const pdfUrl = `${API_BASE}/portal/pay-periods/${periodStart}/report.pdf`;

  const downloadPdf = async () => {
    const token = getToken();
    const res = await fetch(pdfUrl, {
      headers: { Authorization: `Bearer ${token}`, "X-RGTime-Client": "admin" },
    });
    if (!res.ok) throw new Error("PDF download failed");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `rgtime-report-${periodStart}.pdf`;
    a.click();
  };

  const renderTable = (title: string, rows: PayPeriodReport["clean"], className: string) => (
    <div className={`card audit-section ${className}`}>
      <h3>{title}</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Days</th>
            <th>Hours</th>
            <th>Qual≥8</th>
            <th>PTO+</th>
            <th>PTO−</th>
            <th>Balance</th>
            <th>Late</th>
            <th>Wk1</th>
            <th>Wk2</th>
            <th>Absences</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.staff_id}>
              <td>{r.name}</td>
              <td>{r.days_worked}</td>
              <td>{r.total_hours}</td>
              <td>{r.qualifying_days}</td>
              <td>{r.pto_earned}</td>
              <td>{r.pto_used}</td>
              <td>{r.pto_balance}</td>
              <td>{r.late_arrivals}</td>
              <td>{r.week1_hours}</td>
              <td>{r.week2_hours}</td>
              <td className="mono" style={{ fontSize: "0.75rem" }}>
                {Object.entries(r.absences_by_reason)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(", ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div>
      <div className="page-header">
        <h2>Pay-period report</h2>
        <p>Flagged/clean tables with hours, PTO, and absences — download PDF or drill into daily time cards</p>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <div className="card form-grid" style={{ gridTemplateColumns: "240px 1fr auto" }}>
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
        <button type="button" className="btn btn-primary" onClick={() => downloadPdf().catch((e) => setError(String(e)))}>
          Download PDF
        </button>
      </div>

      {report && (
        <>
          {renderTable("Flagged", report.flagged, "audit-flagged")}
          {renderTable("Clean", report.clean, "audit-clean")}
        </>
      )}

      <div className="card">
        <h3>Daily time card drill-down</h3>
        <select value={selectedStaffId} onChange={(e) => setSelectedStaffId(e.target.value)}>
          <option value="">— select staff —</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.staff_code} — {s.first_name} {s.last_name}
            </option>
          ))}
        </select>
        {selectedStaffId && periodStart && (
          <TimeCardView periodStart={periodStart} staffId={selectedStaffId} />
        )}
      </div>
    </div>
  );
}
