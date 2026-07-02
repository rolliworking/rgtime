const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
const TOKEN_KEY = "rgtime_portal_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-RGTime-Client": "admin",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface Staff {
  id: string;
  staff_code: string;
  first_name: string;
  last_name: string;
  hire_date: string;
  face_check_enabled: boolean;
  face_reference_photo_path: string | null;
  auto_clock_out_cap: string;
  is_active: boolean;
  terminated_at: string | null;
  pto_balance: string;
  has_pin: boolean;
  tenure_years: number;
  tenure_label: string;
  pto_rate_per_qualifying_day: string;
  pto_offer_type?: string;
  pto_tenure_credit_years?: number | null;
  pto_custom_annual_hours?: string | null;
  pto_custom_daily_rate?: string | null;
}

export interface OfferTemplate {
  id: string;
  name: string;
  offer_type: string;
  tenure_credit_years?: number | null;
  custom_annual_hours?: string | null;
  custom_daily_rate?: string | null;
}

export interface PtoLadderTier {
  id?: string;
  tier_label: string;
  min_years: number;
  max_years: number | null;
  annual_pto_hours: number;
  rate_per_qualifying_day: string;
  effective_from: string;
}

export interface PayPeriod {
  start_date: string;
  end_date: string;
}

export interface AuditFlag {
  work_date: string;
  flag_type: string;
  detail: string;
}

export interface AuditStaffPeriod {
  staff_id: string;
  staff_code: string;
  first_name: string;
  last_name: string;
  pay_period_start: string;
  pay_period_end: string;
  week1_hours: string;
  week2_hours: string;
  pto_balance: string;
  flags: AuditFlag[];
  bucket: string;
}

export interface SchedulePreset {
  id: string;
  name: string;
  scheduled_start_time: string;
  scheduled_end_time: string;
}

export interface StaffSchedule {
  id: string;
  staff_id: string;
  preset_id: string | null;
  scheduled_start_time: string;
  scheduled_end_time: string;
  effective_from: string | null;
}

export interface AbsenceReason {
  id: string;
  name: string;
  funding: string;
  counts_as_worked: boolean;
  is_active: boolean;
}

export const api = {
  listStaff: (includeTerminated = false) =>
    request<{ staff: Staff[] }>(`/portal/staff?include_terminated=${includeTerminated}`),

  getStaff: (id: string) =>
    request<{ staff: Staff; schedule: StaffSchedule | null }>(`/portal/staff/${id}`),

  createStaff: (body: {
    staff_code: string;
    first_name: string;
    last_name: string;
    hire_date: string;
    auto_clock_out_cap?: string;
    face_check_enabled?: boolean;
    pto_offer_type?: string;
    pto_tenure_credit_years?: number;
    pto_custom_annual_hours?: string;
    pto_custom_daily_rate?: string;
    save_offer_template?: boolean;
    offer_template_name?: string;
  }) => request<Staff>("/portal/staff", { method: "POST", body: JSON.stringify(body) }),

  suggestStaffCode: (first_name: string, last_name = "") =>
    request<{ staff_code: string }>(
      `/portal/staff/suggest-code?first_name=${encodeURIComponent(first_name)}&last_name=${encodeURIComponent(last_name)}`
    ),

  setPtoOffer: (
    id: string,
    body: {
      pto_offer_type: string;
      pto_tenure_credit_years?: number;
      pto_custom_annual_hours?: string;
      pto_custom_daily_rate?: string;
      template_id?: string;
      save_as_template?: boolean;
      template_name?: string;
    }
  ) =>
    request<Staff>(`/portal/staff/${id}/pto-offer`, { method: "PUT", body: JSON.stringify(body) }),

  listOfferTemplates: () => request<{ templates: OfferTemplate[] }>("/portal/offer-templates"),

  getPtoLadder: () =>
    request<{ active: PtoLadderTier[]; history: PtoLadderTier[] }>("/portal/pto-ladder"),

  updatePtoLadder: (body: {
    min_years: number;
    max_years: number | null;
    tier_label: string;
    annual_pto_hours?: number;
    rate_per_qualifying_day?: string;
    effective_from: string;
    confirmed: boolean;
  }) =>
    request<PtoLadderTier>("/portal/pto-ladder", { method: "PUT", body: JSON.stringify(body) }),

  updateStaff: (id: string, body: Partial<Staff>) =>
    request<Staff>(`/portal/staff/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  terminateStaff: (id: string) =>
    request<Staff>(`/portal/staff/${id}/terminate`, { method: "POST" }),

  setPin: (id: string, pin: string) =>
    request<{ ok: boolean }>(`/portal/staff/${id}/pin`, {
      method: "PUT",
      body: JSON.stringify({ pin }),
    }),

  setFaceReference: (id: string, data_base64: string) =>
    request<{ face_reference_photo_path: string }>(`/portal/staff/${id}/face-reference`, {
      method: "POST",
      body: JSON.stringify({ data_base64 }),
    }),

  listPresets: () => request<{ presets: SchedulePreset[] }>("/portal/schedule-presets"),

  createPreset: (body: Omit<SchedulePreset, "id">) =>
    request<SchedulePreset>("/portal/schedule-presets", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setSchedule: (
    staffId: string,
    body: { preset_id?: string; scheduled_start_time?: string; scheduled_end_time?: string }
  ) =>
    request<StaffSchedule>(`/portal/staff/${staffId}/schedule`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  listReasons: () => request<{ reasons: AbsenceReason[] }>("/portal/absence-reasons"),

  createReason: (body: { name: string; funding: string; counts_as_worked: boolean }) =>
    request<AbsenceReason>("/portal/absence-reasons", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateReason: (
    id: string,
    body: Partial<{ name: string; funding: string; counts_as_worked: boolean; is_active: boolean }>
  ) =>
    request<AbsenceReason>(`/portal/absence-reasons/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  listPayPeriods: () =>
    request<{ anchor_date: string; periods: PayPeriod[] }>("/portal/pay-periods"),

  getPeriodAudit: (periodStart: string) =>
    request<{
      pay_period_start: string;
      pay_period_end: string;
      clean: AuditStaffPeriod[];
      flagged: AuditStaffPeriod[];
      clean_count: number;
      flagged_count: number;
    }>(`/portal/pay-periods/${periodStart}/audit`),

  getStaffTimesheet: (periodStart: string, staffId: string) =>
    request<unknown>(`/portal/pay-periods/${periodStart}/staff/${staffId}/timesheet`),

  upsertAbsence: (body: {
    staff_id: string;
    absence_date: string;
    reason_id: string;
    notes?: string;
    pay_period_start?: string;
  }) =>
    request<unknown>("/portal/absences", { method: "POST", body: JSON.stringify(body) }),

  proposePtoDraw: (staffId: string, hours: string) =>
    request<{ hours: string; balance_before: string; balance_after: string }>(
      "/portal/pto-draw/propose",
      { method: "POST", body: JSON.stringify({ staff_id: staffId, hours }) }
    ),

  confirmPtoDraw: (body: {
    staff_id: string;
    hours: string;
    work_date?: string;
    pay_period_start?: string;
    absence_id?: string;
    confirmed: boolean;
  }) =>
    request<unknown>("/portal/pto-draw/confirm", { method: "POST", body: JSON.stringify(body) }),
};
