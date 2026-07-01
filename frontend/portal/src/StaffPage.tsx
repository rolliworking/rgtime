import { FormEvent, useEffect, useState } from "react";
import { SchedulePreset, Staff, api } from "./api";
import { FaceEnrollment } from "./FaceEnrollment";

export function StaffPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [presets, setPresets] = useState<SchedulePreset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [code, setCode] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [hireDate, setHireDate] = useState("");
  const [pin, setPin] = useState("");
  const [presetId, setPresetId] = useState("");

  const load = async () => {
    try {
      const [staffRes, presetRes] = await Promise.all([api.listStaff(true), api.listPresets()]);
      setStaff(staffRes.staff);
      setPresets(presetRes.presets);
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
    setSuccess(null);
    try {
      const created = await api.createStaff({
        staff_code: code,
        first_name: firstName,
        last_name: lastName,
        hire_date: hireDate,
      });
      if (presetId) {
        await api.setSchedule(created.id, { preset_id: presetId });
      }
      if (pin) {
        await api.setPin(created.id, pin);
      }
      setSuccess(`Created ${created.staff_code} — set PIN and schedule applied`);
      setShowCreate(false);
      setSelectedId(created.id);
      setCode("");
      setFirstName("");
      setLastName("");
      setHireDate("");
      setPin("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  const onSetPin = async (id: string) => {
    const newPin = prompt("Enter 4–6 digit PIN for staff:");
    if (!newPin) return;
    try {
      await api.setPin(id, newPin);
      setSuccess("PIN updated");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "PIN failed");
    }
  };

  const onTerminate = async (id: string, staffCode: string) => {
    if (!confirm(`Terminate ${staffCode}? PTO balance will be forfeited.`)) return;
    try {
      await api.terminateStaff(id);
      setSuccess(`${staffCode} terminated`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Terminate failed");
    }
  };

  const selected = staff.find((s) => s.id === selectedId);

  return (
    <div>
      <div className="page-header">
        <h2>Staff</h2>
        <p>Onboard staff — code, hire date, schedule, PIN, face reference</p>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {success && <div className="success-banner">{success}</div>}

      <div className="form-actions" style={{ marginBottom: "1rem" }}>
        <button type="button" className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "Cancel" : "Add staff"}
        </button>
      </div>

      {showCreate && (
        <form className="card" onSubmit={onCreate}>
          <h3>New staff member</h3>
          <div className="form-grid">
            <div className="form-field">
              <label>Staff code</label>
              <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={16} required />
            </div>
            <div className="form-field">
              <label>First name</label>
              <input value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Last name</label>
              <input value={lastName} onChange={(e) => setLastName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Hire date</label>
              <input type="date" value={hireDate} onChange={(e) => setHireDate(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Schedule preset</label>
              <select value={presetId} onChange={(e) => setPresetId(e.target.value)}>
                <option value="">— select —</option>
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.scheduled_start_time.slice(0, 5)}–{p.scheduled_end_time.slice(0, 5)})
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>PIN (4–6 digits)</label>
              <input value={pin} onChange={(e) => setPin(e.target.value)} pattern="\d{4,6}" maxLength={6} />
            </div>
          </div>
          <button type="submit" className="btn btn-primary">
            Create
          </button>
        </form>
      )}

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Hire date</th>
              <th>Tenure</th>
              <th>PIN</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.6 }}>
                <td className="mono">{s.staff_code}</td>
                <td>
                  {s.first_name} {s.last_name}
                </td>
                <td>{s.hire_date}</td>
                <td>
                  <span className="badge">{s.tenure_label}</span>
                </td>
                <td>{s.has_pin ? "Set" : <span className="badge-warn">Missing</span>}</td>
                <td>{s.is_active ? "Active" : "Terminated"}</td>
                <td>
                  <button type="button" className="btn" onClick={() => setSelectedId(s.id)}>
                    Manage
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card">
          <h3>
            {selected.staff_code} — {selected.first_name} {selected.last_name}
          </h3>
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            Tenure: {selected.tenure_label} ({selected.tenure_years} yr) · PTO rate/day:{" "}
            {selected.pto_rate_per_qualifying_day}
          </p>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => onSetPin(selected.id)}>
              Set / reset PIN
            </button>
            {selected.is_active && (
              <button type="button" className="btn btn-danger" onClick={() => onTerminate(selected.id, selected.staff_code)}>
                Terminate
              </button>
            )}
          </div>
          {selected.is_active && (
            <FaceEnrollment staffId={selected.id} onSaved={() => setSuccess("Face reference saved")} />
          )}
        </div>
      )}
    </div>
  );
}
