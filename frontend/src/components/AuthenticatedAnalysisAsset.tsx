import { useEffect, useState, type ReactNode } from "react";
import { fetchActiveAnalysisAsset } from "../api/v2Client";

export function AuthenticatedAnalysisImage({
  taskId,
  suffix,
  alt,
  className
}: {
  taskId: string;
  suffix: string;
  alt: string;
  className?: string;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setSource(null);
    setFailed(false);
    void fetchActiveAnalysisAsset(taskId, suffix).then((blob) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setSource(objectUrl);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [taskId, suffix]);

  return (
    <span>
      <img alt={alt} aria-busy={!source && !failed} className={className} src={source ?? undefined} />
      {failed ? <span className="muted">受保护资产不可用</span> : null}
    </span>
  );
}

export function AuthenticatedAnalysisAssetButton({
  taskId,
  suffix,
  children
}: {
  taskId: string;
  suffix: string;
  children: ReactNode;
}) {
  const [error, setError] = useState(false);

  async function openAsset() {
    setError(false);
    try {
      const blob = await fetchActiveAnalysisAsset(taskId, suffix);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError(true);
    }
  }

  return (
    <>
      <button className="chip" onClick={() => void openAsset()} type="button">{children}</button>
      {error ? <span className="muted">资产不可用</span> : null}
    </>
  );
}
