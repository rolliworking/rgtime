import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api/v1";

type PunchResponse = {
  confirmation: string;
  event_type: string;
  is_late_arrival: boolean;
  lunch_deducted_minutes: number;
  is_missing_clockout_flag: boolean;
  photos_saved: number;
};

type KioskState = {
  display_name: string;
  next_action: string;
  is_clocked_in: boolean;
};

async function capturePhotos(
  video: HTMLVideoElement,
  count = 3,
  intervalMs = 2000,
): Promise<Array<{ sequence_number: number; captured_at: string; data_base64: string }>> {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  if (!ctx) return [];

  const photos: Array<{ sequence_number: number; captured_at: string; data_base64: string }> = [];
  for (let i = 1; i <= count; i++) {
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    photos.push({
      sequence_number: i,
      captured_at: new Date().toISOString(),
      data_base64: canvas.toDataURL("image/jpeg", 0.7),
    });
    if (i < count) {
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }
  return photos;
}

export default function App() {
  const [pin, setPin] = useState("");
  const [state, setState] = useState<KioskState | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user" },
          audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch {
        /* camera optional for dev; photos skipped if unavailable */
      }
    }
    startCamera();
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const appendDigit = (d: string) => {
    if (pin.length < 6) setPin((p) => p + d);
    setError(null);
    setMessage(null);
  };

  const clearPin = () => {
    setPin("");
    setState(null);
    setError(null);
    setMessage(null);
  };

  const lookupState = useCallback(async () => {
    if (pin.length < 4) {
      setError("Enter at least 4 digits");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/kiosk/state`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-RGTime-Client": "kiosk" },
        body: JSON.stringify({ pin }),
      });
      if (!res.ok) throw new Error("Invalid PIN");
      const data: KioskState = await res.json();
      setState(data);
    } catch {
      setError("Invalid PIN — try again");
      setState(null);
    } finally {
      setBusy(false);
    }
  }, [pin]);

  const punch = async () => {
    if (pin.length < 4) {
      setError("Enter at least 4 digits");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      let photos: Array<{ sequence_number: number; captured_at: string; data_base64: string }> = [];
      if (videoRef.current && videoRef.current.readyState >= 2) {
        photos = await capturePhotos(videoRef.current);
      }
      const res = await fetch(`${API_BASE}/kiosk/punch`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-RGTime-Client": "kiosk" },
        body: JSON.stringify({ pin, photos }),
      });
      const data: PunchResponse = await res.json();
      if (!res.ok) throw new Error((data as unknown as { detail: string }).detail ?? "Punch failed");
      setMessage(data.confirmation);
      setState(null);
      setPin("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Punch failed — contact manager");
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
      </header>

      <video ref={videoRef} autoPlay playsInline muted className="camera-preview" />

      {state && (
        <p className="greeting">
          Hello, <strong>{state.display_name}</strong>
        </p>
      )}

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
              if (key === "C") clearPin();
              else if (key === "⌫") setPin((p) => p.slice(0, -1));
              else appendDigit(key);
            }}
          >
            {key}
          </button>
        ))}
      </div>

      <div className="actions">
        <button type="button" className="btn secondary" disabled={busy} onClick={lookupState}>
          Check status
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={punch}>
          {busy ? "…" : actionLabel}
        </button>
      </div>

      {message && <p className="confirmation" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </main>
  );
}
