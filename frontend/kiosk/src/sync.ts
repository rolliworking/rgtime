import { listPendingPunches, QueuedPunch, removePunch } from "./offlineQueue";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api/v1";

export type SyncResult = {
  status: string;
  synced: string[];
  duplicates: string[];
  failures: Array<{ client_local_id: string; error: string }>;
  failure_count: number;
};

export async function syncPendingPunches(): Promise<SyncResult | null> {
  const pending = await listPendingPunches();
  if (pending.length === 0) return null;

  const res = await fetch(`${API_BASE}/kiosk/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-RGTime-Client": "kiosk" },
    body: JSON.stringify({
      punches: pending.map((p) => ({
        client_local_id: p.client_local_id,
        pin: p.pin,
        occurred_at: p.occurred_at,
        photos: p.photos,
      })),
    }),
  });

  const data: SyncResult = await res.json();
  if (!res.ok && res.status >= 500) {
    throw new Error("Sync server error");
  }

  const okIds = new Set([...data.synced, ...data.duplicates]);
  for (const id of okIds) {
    await removePunch(id);
  }
  return data;
}

export async function fetchSyncFailures(): Promise<
  Array<{ id: string; error_message: string; client_local_id: string | null }>
> {
  try {
    const res = await fetch(`${API_BASE}/kiosk/sync-failures`, {
      headers: { "X-RGTime-Client": "kiosk" },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export function newClientLocalId(): string {
  return crypto.randomUUID();
}

export function formatOfflineConfirmation(punch: QueuedPunch): string {
  const local = new Date(punch.occurred_at);
  const timeStr = local.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
  return punch.event_type === "clock_in"
    ? `Clocked in at ${timeStr} (saved offline — will sync)`
    : `Clocked out at ${timeStr} (saved offline — will sync)`;
}
