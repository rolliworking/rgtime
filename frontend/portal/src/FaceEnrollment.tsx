import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

interface Props {
  staffId: string;
  onSaved: () => void;
}

export function FaceEnrollment({ staffId, onSaved }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user" }, audio: false })
      .then((s) => {
        stream = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => setError("Camera unavailable — upload skipped (NEEDS MICHAEL for manual path)"));

    return () => {
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    setPreview(canvas.toDataURL("image/jpeg", 0.85));
  }, []);

  const save = async () => {
    if (!preview) return;
    setSaving(true);
    setError(null);
    try {
      await api.setFaceReference(staffId, preview);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <h3>Face reference photo</h3>
      <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
        Capture one reference frame (same JPEG format as kiosk punches).
      </p>
      {error && <div className="error-banner">{error}</div>}
      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        <video ref={videoRef} autoPlay playsInline muted width={200} height={150} style={{ borderRadius: 4 }} />
        {preview && <img src={preview} alt="Captured" className="face-preview" />}
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={capture}>
          Capture
        </button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={!preview || saving}>
          {saving ? "Saving…" : "Save reference"}
        </button>
      </div>
    </div>
  );
}
