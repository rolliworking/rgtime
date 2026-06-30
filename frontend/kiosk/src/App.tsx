import { useCallback, useEffect, useRef, useState } from "react";
import {
  enqueuePunch,
  listPendingPunches,
  pendingCount,
  QueuedPunch,
} from "./offlineQueue";
import {
  fetchSyncFailures,
  formatOfflineConfirmation,
  newClientLocalId,
  syncPendingPunches,
} from "./sync";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api/v1";

type PunchResponse = {
  confirmation: string;
};

type KioskState = {
  display_name: string;
  next_action: string;
};

async function capturePhotos(
  video: HTMLVideoElement,
  count = 3,
  intervalMs = 2000,
): Promise<QueuedPunch["photos"]> {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  if (!ctx) return [];

  const photos: QueuedPunch["photos"] = [];
  for (let i = 1; i <= count; i++) {
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    photos.push({
      sequence_number: i,
      captured_at: new Date().toISOString(),
      data_base64: canvas.toDataURL("image/jpeg", 0.7),
    });
    if (i < count) await new Promise((r) => setTimeout(r, intervalMs));
  }
  return photos;
}

function deriveNextAction(pending: QueuedPunch[], pin: string): "clock_in" | "clock_out" {
  const mine = pending
    .filter((p) => p.pin === pin)
    .sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
  let clockedIn = false;
  for (const p of mine) {
    clockedIn = p.event_type === "clock_in";
  }
  return clockedIn ? "clock_out" : "clock_in";
}

export default function App() {
  const [pin, setPin] = useState("");
  const [state, setState] = useState<KioskState | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [queueSize, setQueueSize] = useState(0);
  const [syncAlert, setSyncAlert] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const refreshQueue = useCallback(async () => {
    setQueueSize(await pendingCount());
  }, []);

  const runSync = useCallback(async () => {
    if (!navigator.onLine) return;
    try {
      const result = await syncPendingPunches();
      await refreshQueue();
      if (result && result.failure_count > 0) {
        setSyncAlert(
          `SYNC FAILED: ${result.failure_count} punch(es) could not sync — manager notified`,
        );
      } else if (result && result.synced.length > 0) {
        setMessage(`Synced ${result.synced.length} offline punch(es)`);
      }
      const failures = await fetchSyncFailures();
      if (failures.length > 0) {
        setSyncAlert(`MANAGER ALERT: ${failures.length} unresolved sync failure(s)`);
      }
    } catch {
      setSyncAlert("SYNC FAILED — punches remain queued; manager will be alerted on retry");
    }
  }, [refreshQueue]);

  useEffect(() => {
    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user" },
          audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      } catch {
        /* optional */
      }
    }
    startCamera();
    refreshQueue();
    runSync();
    return () => streamRef.current?.getTracks().forEach((t) => t.stop());
  }, [refreshQueue, runSync]);

  useEffect(() => {
    const onOnline = () => {
      setOffline(false);
      runSync();
    };
    const onOffline = () => setOffline(true);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [runSync]);

  const punch = async () => {
    if (pin.length < 4) {
      setError("Enter at least 4 digits");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    setSyncAlert(null);

    const occurred_at = new Date().toISOString();
    const client_local_id = newClientLocalId();
    let photos: QueuedPunch["photos"] = [];
    if (videoRef.current && videoRef.current.readyState >= 2) {
      photos = await capturePhotos(videoRef.current);
    }

    const pending = await listPendingPunches();
    const event_type = deriveNextAction(pending, pin);

    if (!navigator.onLine) {
      const queued: QueuedPunch = {
        client_local_id,
        pin,
        occurred_at,
        event_type,
        photos,
        confirmation: "",
      };
      queued.confirmation = formatOfflineConfirmation(queued);
      await enqueuePunch(queued);
      await refreshQueue();
      setMessage(queued.confirmation);
      setPin("");
      setState(null);
      setBusy(false);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/kiosk/punch`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-RGTime-Client": "kiosk" },
        body: JSON.stringify({ pin, photos, client_local_id }),
      });
      if (!res.ok) throw new Error("Punch failed");
      const data: PunchResponse = await res.json();
      setMessage(data.confirmation);
      setPin("");
      setState(null);
    } catch {
      const queued: QueuedPunch = {
        client_local_id,
        pin,
        occurred_at,
        event_type,
        photos,
        confirmation: "",
      };
      queued.confirmation = formatOfflineConfirmation(queued);
      await enqueuePunch(queued);
      await refreshQueue();
      setMessage(queued.confirmation);
      setPin("");
      setState(null);
    } finally {
      setBusy(false);
    }
  };

  const actionLabel =
    state?.next_action === "clock_out" ? "Clock Out" : "Clock In";

  return (
    <main className="kiosk-shell">
      <header>
        <h1>RG Time</h1>
        <p className="subtitle">Workshop Kiosk</p>
        {offline && <p className="offline-banner">OFFLINE — punches saved locally</p>}
        {queueSize > 0 && <p className="queue-banner">{queueSize} punch(es) waiting to sync</p>}
      </header>

      <video ref={videoRef} autoPlay playsInline muted className="camera-preview" />

      <div className="pin-display" aria-label="PIN entry">
        {"•".repeat(pin.length).padEnd(6, "○")}
      </div>

      <div className="keypad">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "⌫"].map((key) => (
          <button
            key={key}
            type="button"
            className="key"
            disabled={busy}
            onClick={() => {
              if (key === "C") {
                setPin("");
                setState(null);
              } else if (key === "⌫") setPin((p) => p.slice(0, -1));
              else if (pin.length < 6) setPin((p) => p + key);
            }}
          >
            {key}
          </button>
        ))}
      </div>

      <div className="actions">
        <button type="button" className="btn primary" disabled={busy} onClick={punch}>
          {busy ? "…" : actionLabel}
        </button>
      </div>

      {message && (
        <p className="confirmation" role="status">
          {message}
        </p>
      )}
      {syncAlert && (
        <p className="sync-alert" role="alert">
          {syncAlert}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
