import { FormEvent, useEffect, useState } from "react";
import { AbsenceReason, api } from "./api";

const FUNDING_OPTIONS = [
  { value: "paid_outright", label: "Paid outright" },
  { value: "paid_from_pto", label: "Paid from PTO" },
  { value: "unpaid_pto_coverable", label: "Unpaid (PTO coverable)" },
  { value: "unpaid", label: "Unpaid" },
];

export function AbsenceReasonsPage() {
  const [reasons, setReasons] = useState<AbsenceReason[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [funding, setFunding] = useState("unpaid");
  const [countsAsWorked, setCountsAsWorked] = useState(false);

  const load = async () => {
    try {
      const res = await api.listReasons();
      setReasons(res.reasons);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.createReason({ name, funding, counts_as_worked: countsAsWorked });
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  const toggleActive = async (r: AbsenceReason) => {
    try {
      await api.updateReason(r.id, { is_active: !r.is_active });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Absence reasons</h2>
        <p>Editable library — funding axis + counts_as_worked</p>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <form className="card" onSubmit={onCreate}>
        <h3>Add reason</h3>
        <div className="form-grid">
          <div className="form-field">
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>Funding</label>
            <select value={funding} onChange={(e) => setFunding(e.target.value)}>
              {FUNDING_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>
              <input
                type="checkbox"
                checked={countsAsWorked}
                onChange={(e) => setCountsAsWorked(e.target.checked)}
              />{" "}
              Counts as worked
            </label>
          </div>
        </div>
        <button type="submit" className="btn btn-primary">
          Add
        </button>
      </form>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Funding</th>
              <th>Counts as worked</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {reasons.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td className="mono">{r.funding}</td>
                <td>{r.counts_as_worked ? "Yes" : "No"}</td>
                <td>
                  {r.is_active ? <span className="badge">Active</span> : <span className="badge-muted">Inactive</span>}
                </td>
                <td>
                  <button type="button" className="btn" onClick={() => toggleActive(r)}>
                    {r.is_active ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
