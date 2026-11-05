import { useRef, useState } from "react";

import { ApiError } from "@/api/errors";

import { uploadFileToPresignedUrl, type PresignedUploadHandle } from "./upload";

export interface AssetUploadArgs { name: string; file: File }
export interface AssetUploadState {
  phase: "idle" | "uploading" | "error";
  progress: number;
  statusText: string;
  error: string | null;
}

interface UploadServices<T> {
  initiate: (args: T) => Promise<{ upload_token: string; presigned_url: string }>;
  complete: (token: string) => Promise<unknown>;
  cancel: (token: string) => void;
}

const IDLE: AssetUploadState = { phase: "idle", progress: 0, statusText: "", error: null };

export function formatUploadLimit(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  return bytes >= 1024 * 1024 ? `${Math.floor(bytes / 1024 / 1024)} MB` : `${Math.floor(bytes / 1024)} KB`;
}

/** One signed-upload state machine; generation checks keep stale responses out of a newer upload. */
export function useAssetUpload<T extends AssetUploadArgs>({ maxSizeBytes, label, services }: {
  maxSizeBytes: number | undefined; label: string; services: UploadServices<T>;
}) {
  const [state, setState] = useState<AssetUploadState>(IDLE);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const token = useRef<string | null>(null);
  const put = useRef<PresignedUploadHandle | null>(null);

  async function upload(args: T, current: number) {
    const active = () => current === generation.current;
    try {
      const issued = await services.initiate(args);
      if (!active()) { services.cancel(issued.upload_token); return; }
      token.current = issued.upload_token;
      setState(previous => ({ ...previous, statusText: "Uploading…" }));
      const handle = uploadFileToPresignedUrl(issued.presigned_url, args.file, percent => {
        if (active()) setState(previous => ({ ...previous, progress: percent, statusText: `Uploading… ${percent}%` }));
      });
      put.current = handle;
      await handle.promise;
      if (!active()) return;
      setState(previous => ({ ...previous, statusText: "Finalizing…" }));
      await services.complete(issued.upload_token);
      if (active()) setState(IDLE);
    } catch (error) {
      if (!active()) return;
      const message = error instanceof ApiError || error instanceof Error ? error.message : "Upload failed.";
      setState({ phase: "error", progress: 0, statusText: "", error: message });
      if (token.current) services.cancel(token.current);
    } finally {
      if (active()) { inFlight.current = false; put.current = null; token.current = null; }
    }
  }

  function start(args: T) {
    if (inFlight.current) return;
    let error: string | null = null;
    if (!args.name.trim()) error = `${label} name is required.`;
    else if (maxSizeBytes === undefined) error = "Upload limit is unavailable right now. Please retry in a moment.";
    else if (args.file.size > maxSizeBytes) error = `File size exceeds the maximum (${formatUploadLimit(maxSizeBytes)}).`;
    else if (args.file.size === 0) error = "Choose a nonempty file.";
    if (error) { setState({ phase: "error", progress: 0, statusText: "", error }); return; }
    inFlight.current = true;
    token.current = null;
    put.current = null;
    setState({ phase: "uploading", progress: 0, statusText: "Preparing upload…", error: null });
    void upload({ ...args, name: args.name.trim() }, ++generation.current);
  }

  function cancel() {
    if (!inFlight.current) return;
    ++generation.current;
    put.current?.abort();
    if (token.current) services.cancel(token.current);
    inFlight.current = false;
    put.current = null;
    token.current = null;
    setState(IDLE);
  }

  return { ...state, start, cancel };
}
