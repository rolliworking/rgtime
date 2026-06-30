/**
 * IndexedDB offline punch queue for kiosk resilience (Phase 2).
 */

export type QueuedPunch = {
  client_local_id: string;
  pin: string;
  occurred_at: string;
  event_type: "clock_in" | "clock_out";
  photos: Array<{ sequence_number: number; captured_at: string; data_base64: string }>;
  confirmation: string;
};

const DB_NAME = "rgtime-kiosk";
const DB_VERSION = 1;
const STORE = "pending_punches";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onerror = () => reject(req.error);
    req.onsuccess = () => resolve(req.result);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "client_local_id" });
        store.createIndex("occurred_at", "occurred_at", { unique: false });
      }
    };
  });
}

export async function enqueuePunch(punch: QueuedPunch): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(punch);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function listPendingPunches(): Promise<QueuedPunch[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => {
      const items = (req.result as QueuedPunch[]).sort((a, b) =>
        a.occurred_at.localeCompare(b.occurred_at),
      );
      resolve(items);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function removePunch(clientLocalId: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(clientLocalId);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function pendingCount(): Promise<number> {
  const items = await listPendingPunches();
  return items.length;
}
