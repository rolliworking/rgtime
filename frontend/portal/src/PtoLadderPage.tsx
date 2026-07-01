import { FormEvent, useEffect, useState } from "react";
import { OfferTemplate, PtoLadderTier, api } from "./api";

export function PtoLadderPage() {
  const [active, setActive] = useState<PtoLadderTier[]>([]);
  const [history, setHistory] = useState<PtoLadderTier[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editing, setEditing] = useState<PtoLadderTier | null>(null);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [annualHours, setAnnualHours] = useState("");
  const [dailyRate, setDailyRate] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const load = async () => {
    try {
      const res = await api.getPtoLadder();
      setActive(res.active);
      setHistory(res.history);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const startEdit = (tier: PtoLadderTier) => {
    setEditing(tier);
    setAnnualHours(String(tier.annual_pto_hours));
    setDailyRate(tier.rate_per_qualifying_day);
    setEffectiveFrom("");
    setConfirmed(false);
    setSuccess(null);
    setError(null);
  };

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    if (!effectiveFrom) {
      setError("effective_from date is required");
      return;
    }
    if (!confirmed) {
      setError("Check the confirmation box — this affects all staff going forward from that date");
      return;
    }
    setError(null);
    try {
      await api.updatePtoLadder({
        min_years: editing.min_years,
        max_years: editing.max_years,
        tier_label: editing.tier_label,
        annual_pto_hours: annualHours ? Number(annualHours) : undefined,
        rate_per_qualifying_day: dailyRate || undefined,
        effective_from: effectiveFrom,
        confirmed: true,
      });
      setSuccess(`Updated ${editing.tier_label} effective ${effectiveFrom}`);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>PTO Ladder</h2>
        <p>Effective-dated tenure tiers — changes apply forward only from the chosen date</p>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {success && <div className="success-banner">{success}</div>}

      <div className="card">
        <h3>Currently active rates</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Tier</th>
              <th>Annual hrs</th>
              <th>Per qualifying day</th>
              <th>Effective from</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {active.map((t) => (
              <tr key={`${t.min_years}-${t.effective_from}`}>
                <td>{t.tier_label}</td>
                <td>{t.annual_pto_hours}</td>
                <td className="mono">{t.rate_per_qualifying_day}</td>
                <td>{t.effective_from}</td>
                <td>
                  <button type="button" className="btn" onClick={() => startEdit(t)}>
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <form className="card" onSubmit={onSave}>
          <h3>
            Edit {editing.tier_label} — affects all staff going forward from effective date
          </h3>
          <div className="form-grid">
            <div className="form-field">
              <label>Annual PTO hours</label>
              <input
                type="number"
                value={annualHours}
                onChange={(e) => setAnnualHours(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label>Rate per qualifying day</label>
              <input value={dailyRate} onChange={(e) => setDailyRate(e.target.value)} />
            </div>
            <div className="form-field">
              <label>Effective from</label>
              <input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
                required
              />
            </div>
          </div>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "1rem" }}>
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            Confirm: this affects all staff going forward from {effectiveFrom || "[date]"}
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary">
              Save ladder change
            </button>
            <button type="button" className="btn" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="card">
        <h3>Version history</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Tier</th>
              <th>Annual hrs</th>
              <th>Rate/day</th>
              <th>Effective from</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id ?? `${h.min_years}-${h.effective_from}`}>
                <td>{h.tier_label}</td>
                <td>{h.annual_pto_hours}</td>
                <td className="mono">{h.rate_per_qualifying_day}</td>
                <td>{h.effective_from}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
