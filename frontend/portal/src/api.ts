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
  }) => request<Staff>("/portal/staff", { method: "POST", body: JSON.stringify(body) }),

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
};
