import { FormEvent, useEffect, useState } from "react";
import { api, SchedulePreset } from "./api";

export function SchedulesPage() {
  const [presets, setPresets] = useState<SchedulePreset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");

  const load = async () => {
    try {
      const res = await api.listPresets();
      setPresets(res.presets);
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
      await api.createPreset({
        name,
        scheduled_start_time: `${start}:00`,
        scheduled_end_time: `${end}:00`,
      });
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Schedule presets</h2>
        <p>Reusable start/end times assigned per staff member</p>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <form className="card" onSubmit={onCreate}>
        <h3>Add preset</h3>
        <div className="form-grid">
          <div className="form-field">
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>Start</label>
            <input type="time" value={start} onChange={(e) => setStart(e.target.value)} required />
          </div>
          <div className="form-field">
            <label>End</label>
            <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </div>
        </div>
        <button type="submit" className="btn btn-primary">
          Add preset
        </button>
      </form>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Start</th>
              <th>End</th>
            </tr>
          </thead>
          <tbody>
            {presets.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="mono">{p.scheduled_start_time.slice(0, 5)}</td>
                <td className="mono">{p.scheduled_end_time.slice(0, 5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
