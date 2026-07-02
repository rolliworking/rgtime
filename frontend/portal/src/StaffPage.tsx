import { FormEvent, useEffect, useState } from "react";
import { OfferTemplate, SchedulePreset, Staff, api } from "./api";
import { FaceEnrollment } from "./FaceEnrollment";

type PtoOfferMode = "default" | "custom";
type CustomOfferKind = "tenure_credit" | "custom_rate";

export function StaffPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [presets, setPresets] = useState<SchedulePreset[]>([]);
  const [templates, setTemplates] = useState<OfferTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [code, setCode] = useState("");
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [lastName, setLastName] = useState("");
  const [hireDate, setHireDate] = useState("");
  const [pin, setPin] = useState("");
  const [presetId, setPresetId] = useState("");

  const [offerMode, setOfferMode] = useState<PtoOfferMode>("default");
  const [customKind, setCustomKind] = useState<CustomOfferKind>("tenure_credit");
  const [tenureCredit, setTenureCredit] = useState("3");
  const [annualHours, setAnnualHours] = useState("80");
  const [dailyRate, setDailyRate] = useState("");
  const [saveTemplate, setSaveTemplate] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  const [editOfferMode, setEditOfferMode] = useState<PtoOfferMode>("default");
  const [editCustomKind, setEditCustomKind] = useState<CustomOfferKind>("tenure_credit");
  const [editTenureCredit, setEditTenureCredit] = useState("0");
  const [editAnnualHours, setEditAnnualHours] = useState("");
  const [editDailyRate, setEditDailyRate] = useState("");
  const [editMiddleName, setEditMiddleName] = useState("");

  const load = async () => {
    try {
      const [staffRes, presetRes, tplRes] = await Promise.all([
        api.listStaff(true),
        api.listPresets(),
        api.listOfferTemplates(),
      ]);
      setStaff(staffRes.staff);
      setPresets(presetRes.presets);
      setTemplates(tplRes.templates);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const suggestCode = async (first: string, middle: string, last: string) => {
    if (!first.trim() || !last.trim()) return;
    try {
      const res = await api.suggestStaffCode(first, last, middle);
      setCode(res.staff_code);
    } catch {
      /* non-fatal */
    }
  };

  useEffect(() => {
    if (showCreate && firstName.trim() && lastName.trim()) {
      const t = setTimeout(() => suggestCode(firstName, middleName, lastName), 300);
      return () => clearTimeout(t);
    }
  }, [firstName, middleName, lastName, showCreate]);

  const ptoPayload = () => {
    if (offerMode === "default") {
      return { pto_offer_type: "default" as const };
    }
    if (customKind === "tenure_credit") {
      return {
        pto_offer_type: "tenure_credit" as const,
        pto_tenure_credit_years: Number(tenureCredit),
      };
    }
    return {
      pto_offer_type: "custom_rate" as const,
      pto_custom_annual_hours: annualHours || undefined,
      pto_custom_daily_rate: dailyRate || undefined,
    };
  };

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    try {
      const created = await api.createStaff({
        staff_code: code,
        first_name: firstName,
        middle_name: middleName.trim() || undefined,
        last_name: lastName,
        hire_date: hireDate,
        ...ptoPayload(),
        save_offer_template: saveTemplate && offerMode === "custom",
        offer_template_name: templateName || undefined,
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
      setMiddleName("");
      setLastName("");
      setHireDate("");
      setPin("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  const onSavePtoOffer = async () => {
    if (!selectedId) return;
    setError(null);
    try {
      if (editTemplateId) {
        await api.setPtoOffer(selectedId, { pto_offer_type: "default", template_id: editTemplateId });
      } else if (editOfferMode === "default") {
        await api.setPtoOffer(selectedId, { pto_offer_type: "default" });
      } else if (editCustomKind === "tenure_credit") {
        await api.setPtoOffer(selectedId, {
          pto_offer_type: "tenure_credit",
          pto_tenure_credit_years: Number(editTenureCredit),
        });
      } else {
        await api.setPtoOffer(selectedId, {
          pto_offer_type: "custom_rate",
          pto_custom_annual_hours: editAnnualHours || undefined,
          pto_custom_daily_rate: editDailyRate || undefined,
        });
      }
      setSuccess("PTO offer updated");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "PTO offer update failed");
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

  const onSaveProfile = async () => {
    if (!selectedId) return;
    setError(null);
    try {
      await api.updateStaff(selectedId, { middle_name: editMiddleName.trim() || null });
      setSuccess("Profile updated");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profile update failed");
    }
  };

  const staffLabel = (s: Staff) => s.display_name ?? `${s.first_name} ${s.last_name}`;

  const selected = staff.find((s) => s.id === selectedId);

  useEffect(() => {
    if (!selected) return;
    const t = selected.pto_offer_type ?? "default";
    if (t === "default") {
      setEditOfferMode("default");
    } else {
      setEditOfferMode("custom");
      setEditCustomKind(t === "tenure_credit" ? "tenure_credit" : "custom_rate");
      setEditTenureCredit(String(selected.pto_tenure_credit_years ?? 0));
      setEditAnnualHours(selected.pto_custom_annual_hours ?? "");
      setEditDailyRate(selected.pto_custom_daily_rate ?? "");
    }
    setEditTemplateId("");
    setEditMiddleName(selected.middle_name ?? "");
  }, [selectedId, selected?.pto_offer_type, selected?.middle_name]);

  return (
    <div>
      <div className="page-header">
        <h2>Staff</h2>
        <p>Onboard staff — code, hire date, PTO offer, schedule, PIN, face reference</p>
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
              <label>First name</label>
              <input value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Middle name (optional)</label>
              <input value={middleName} onChange={(e) => setMiddleName(e.target.value)} />
            </div>
            <div className="form-field">
              <label>Last name</label>
              <input value={lastName} onChange={(e) => setLastName(e.target.value)} required />
            </div>
            <div className="form-field">
              <label>Staff code (suggested — editable)</label>
              <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={16} required />
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

          <fieldset className="card" style={{ marginTop: "1rem", border: "1px solid var(--border)" }}>
            <legend>PTO Offer</legend>
            <label style={{ display: "block", marginBottom: "0.5rem" }}>
              <input
                type="radio"
                checked={offerMode === "default"}
                onChange={() => setOfferMode("default")}
              />{" "}
              Default — standard tenure ladder
            </label>
            <label style={{ display: "block", marginBottom: "0.75rem" }}>
              <input
                type="radio"
                checked={offerMode === "custom"}
                onChange={() => setOfferMode("custom")}
              />{" "}
              Custom offer
            </label>
            {offerMode === "custom" && (
              <div className="form-grid">
                <div className="form-field">
                  <label>Apply saved template</label>
                  <select
                    value={selectedTemplateId}
                    onChange={(e) => {
                      const id = e.target.value;
                      setSelectedTemplateId(id);
                      const tpl = templates.find((t) => t.id === id);
                      if (!tpl) return;
                      setOfferMode("custom");
                      setCustomKind(tpl.offer_type as CustomOfferKind);
                      if (tpl.offer_type === "tenure_credit") {
                        setTenureCredit(String(tpl.tenure_credit_years ?? 0));
                      } else {
                        setAnnualHours(tpl.custom_annual_hours ?? "");
                        setDailyRate(tpl.custom_daily_rate ?? "");
                      }
                    }}
                  >
                    <option value="">— enter manually —</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>Offer type</label>
                  <select value={customKind} onChange={(e) => setCustomKind(e.target.value as CustomOfferKind)}>
                    <option value="tenure_credit">Start at tenure tier N (credit years)</option>
                    <option value="custom_rate">Custom rate / annual hours</option>
                  </select>
                </div>
                {customKind === "tenure_credit" ? (
                  <div className="form-field">
                    <label>Tenure credit (years)</label>
                    <input
                      type="number"
                      min={0}
                      value={tenureCredit}
                      onChange={(e) => setTenureCredit(e.target.value)}
                    />
                  </div>
                ) : (
                  <>
                    <div className="form-field">
                      <label>Annual PTO hours</label>
                      <input value={annualHours} onChange={(e) => setAnnualHours(e.target.value)} />
                    </div>
                    <div className="form-field">
                      <label>Or per-day rate</label>
                      <input value={dailyRate} onChange={(e) => setDailyRate(e.target.value)} />
                    </div>
                  </>
                )}
                <div className="form-field">
                  <label>
                    <input
                      type="checkbox"
                      checked={saveTemplate}
                      onChange={(e) => setSaveTemplate(e.target.checked)}
                    />{" "}
                    Save as template
                  </label>
                  {saveTemplate && (
                    <input
                      placeholder="Template name"
                      value={templateName}
                      onChange={(e) => setTemplateName(e.target.value)}
                    />
                  )}
                </div>
              </div>
            )}
          </fieldset>

          <button type="submit" className="btn btn-primary" style={{ marginTop: "1rem" }}>
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
              <th>PTO offer</th>
              <th>PIN</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.6 }}>
                <td className="mono">{s.staff_code}</td>
                <td>{staffLabel(s)}</td>
                <td>{s.hire_date}</td>
                <td>
                  <span className="badge">{s.tenure_label}</span>
                </td>
                <td>{s.pto_offer_type ?? "default"}</td>
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
            {selected.staff_code} — {staffLabel(selected)}
          </h3>

          <fieldset className="card" style={{ marginTop: "1rem", border: "1px solid var(--border)" }}>
            <legend>Name</legend>
            <div className="form-grid">
              <div className="form-field">
                <label>Middle name</label>
                <input value={editMiddleName} onChange={(e) => setEditMiddleName(e.target.value)} />
              </div>
            </div>
            <button type="button" className="btn" onClick={onSaveProfile} style={{ marginTop: "0.5rem" }}>
              Save name
            </button>
          </fieldset>

          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            Tenure: {selected.tenure_label} ({selected.tenure_years} yr) · PTO rate/day:{" "}
            {selected.pto_rate_per_qualifying_day} · Offer: {selected.pto_offer_type ?? "default"}
          </p>

          <fieldset className="card" style={{ marginTop: "1rem", border: "1px solid var(--border)" }}>
            <legend>PTO Offer</legend>
            <label style={{ display: "block", marginBottom: "0.5rem" }}>
              <input
                type="radio"
                checked={editOfferMode === "default"}
                onChange={() => setEditOfferMode("default")}
              />{" "}
              Default
            </label>
            <label style={{ display: "block", marginBottom: "0.75rem" }}>
              <input
                type="radio"
                checked={editOfferMode === "custom"}
                onChange={() => setEditOfferMode("custom")}
              />{" "}
              Custom
            </label>
            <div className="form-field" style={{ marginBottom: "0.75rem" }}>
              <label>Apply saved template</label>
              <select value={editTemplateId} onChange={(e) => setEditTemplateId(e.target.value)}>
                <option value="">— none —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            {editOfferMode === "custom" && !editTemplateId && (
              <div className="form-grid">
                <div className="form-field">
                  <label>Offer type</label>
                  <select
                    value={editCustomKind}
                    onChange={(e) => setEditCustomKind(e.target.value as CustomOfferKind)}
                  >
                    <option value="tenure_credit">Tenure credit</option>
                    <option value="custom_rate">Custom rate / annual</option>
                  </select>
                </div>
                {editCustomKind === "tenure_credit" ? (
                  <div className="form-field">
                    <label>Credit years</label>
                    <input
                      type="number"
                      min={0}
                      value={editTenureCredit}
                      onChange={(e) => setEditTenureCredit(e.target.value)}
                    />
                  </div>
                ) : (
                  <>
                    <div className="form-field">
                      <label>Annual hours</label>
                      <input value={editAnnualHours} onChange={(e) => setEditAnnualHours(e.target.value)} />
                    </div>
                    <div className="form-field">
                      <label>Per-day rate</label>
                      <input value={editDailyRate} onChange={(e) => setEditDailyRate(e.target.value)} />
                    </div>
                  </>
                )}
              </div>
            )}
            <button type="button" className="btn btn-primary" onClick={onSavePtoOffer} style={{ marginTop: "0.5rem" }}>
              Save PTO offer
            </button>
          </fieldset>

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
