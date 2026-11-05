import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";

import { useQueryClient } from "@tanstack/react-query";

import { ctfKeys, useCtfContentImages, useCtfCurrentEvent } from "@/api/ctf";
import { useCtfInboxCrossTabSync, useCtfInboxRefetch, useCtfInboxSummary } from "@/api/ctfInbox";
import {
  Toast,
  ToastAction,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast";

import { openReconnectingSocket, sameOriginSocketUrl } from "@/lib/reconnectingSocket";

import { ContentImageProvider } from "./contentImages";
import { ctfInboxPath, ctfRangePath, ctfScoreboardPath } from "./routes";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Hint = "communication" | "refresh" | "position_changed" | "range_ready";
type ToastKind = Exclude<Hint, "refresh">;

/** Content-free hint kinds that carry no fields besides their kind (ADR-072-R4). */
const BARE_HINTS: ReadonlySet<string> = new Set(["refresh", "position_changed", "range_ready"]);

// shared.enums.WebSocketCloseCode.SERVICE_UNAVAILABLE: the shared bus is parked.
const BUS_PARKED_CLOSE_CODE = 4503;

interface BusFrame {
  type?: unknown;
  topic?: unknown;
  payload?: { kind?: unknown; snapshot_id?: unknown; intent_id?: unknown };
}

/**
 * Classify one shared-bus frame for this event's topic. The server projects
 * every frame to a reference-only `communication` hint, a bare
 * `position_changed` or `range_ready` hint, or a generic `refresh` hint
 * (ADR-051-R6, ADR-072-R4); anything else, including a legacy content-bearing
 * frame, is dropped. A hint never carries content and never grants access.
 */
function classifyFrame(raw: string, topic: string): Hint | null {
  let frame: BusFrame;
  try {
    frame = JSON.parse(raw) as BusFrame;
  } catch {
    return null;
  }
  if (frame?.type !== "notification" || frame.topic !== topic || !frame.payload) return null;
  const { kind, snapshot_id: snapshotId, intent_id: intentId } = frame.payload;
  if (typeof kind === "string" && BARE_HINTS.has(kind)) return kind as Hint;
  const isRef = (value: unknown) => typeof value === "string" && UUID.test(value);
  return kind === "communication" && isRef(snapshotId) && isRef(intentId) ? "communication" : null;
}

/**
 * Live hints for the active event over the shared WS bus (CTF-802, #2053).
 * Opens no socket unless the event selects a live notification kind, and
 * reconnects with bounded backoff while it does.
 */
function useEventHints(eventId: string | undefined, enabled: boolean, onHint: (hint: Hint) => void) {
  const handler = useRef(onHint);
  handler.current = onHint;

  useEffect(() => {
    if (!eventId || !enabled || typeof WebSocket === "undefined") return;
    const topic = `ctf:event:${eventId}`;
    return openReconnectingSocket(sameOriginSocketUrl("/ws/notifications/"), {
      onOpen: (socket) => socket.send(JSON.stringify({ type: "subscribe", topic })),
      onMessage: (data) => {
        const hint = classifyFrame(data, topic);
        if (hint) handler.current(hint);
      },
      terminalCloseCodes: [BUS_PARKED_CLOSE_CODE],
    });
  }, [eventId, enabled]);
}

/**
 * Non-modal notice for messages whose pinned policy still needs an action. It
 * is a polite status region: it never takes focus, never blocks navigation and
 * disappears when the obligations are met (WCAG 2.1.2).
 */
function ActionRequiredNotice({ eventId }: Readonly<{ eventId: string | undefined }>) {
  const { pathname } = useLocation();
  const summary = useCtfInboxSummary(eventId);
  const count = summary.isError ? 0 : (summary.data?.action_required_count ?? 0);
  if (count === 0 || pathname.startsWith(ctfInboxPath())) return null;
  return (
    <output className="mx-auto mb-4 flex max-w-5xl flex-wrap items-center gap-3 rounded-md border px-4 py-2 text-sm">
      <span>{count === 1 ? "1 message needs your action." : `${count} messages need your action.`}</span>
      <Link className="underline" to={`${ctfInboxPath()}?view=action_required`}>
        Review messages
      </Link>
    </output>
  );
}

interface LiveToast {
  id: number;
  kind: ToastKind;
}

/** Participant workspace shell: routes render through the outlet with live hints on top. */
export function CtfWorkspaceLayout() {
  const { data } = useCtfCurrentEvent();
  const eventId = data?.event.id;
  const liveEnabled = (data?.event.live_notifications?.length ?? 0) > 0;
  const contentImages = useCtfContentImages();
  const queryClient = useQueryClient();
  const refetchInbox = useCtfInboxRefetch();
  const [toasts, setToasts] = useState<LiveToast[]>([]);
  const nextId = useRef(0);

  useCtfInboxCrossTabSync(eventId);

  const onHint = useCallback(
    (hint: Hint) => {
      if (!eventId) return;
      if (hint === "communication") {
        void refetchInbox(eventId);
      } else {
        void queryClient.invalidateQueries({ queryKey: ctfKeys.all });
      }
      if (hint === "refresh") return;
      nextId.current += 1;
      setToasts((current) => [...current.slice(-3), { id: nextId.current, kind: hint }]);
    },
    [eventId, queryClient, refetchInbox],
  );

  useEventHints(eventId, liveEnabled, onHint);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastProvider>
      <ActionRequiredNotice eventId={eventId} />
      <ContentImageProvider images={contentImages.data?.images}>
        <Outlet />
      </ContentImageProvider>
      {toasts.map((toast) => (
        <LiveHintToast key={toast.id} id={toast.id} kind={toast.kind} onDismiss={dismiss} />
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}

/** Fixed, content-free toast text; detail is read only through authenticated pages. */
const TOAST_TEXT: Record<ToastKind, { title: string; description: string; action: string; to: () => string }> = {
  communication: {
    title: "New message",
    description: "A new message is in your inbox.",
    action: "Open inbox",
    to: ctfInboxPath,
  },
  position_changed: {
    title: "Scoreboard position changed",
    description: "Your position on the scoreboard changed.",
    action: "Open scoreboard",
    to: ctfScoreboardPath,
  },
  range_ready: {
    title: "Range ready",
    description: "Your range is ready.",
    action: "Open range",
    to: ctfRangePath,
  },
};

function LiveHintToast({
  id,
  kind,
  onDismiss,
}: Readonly<{ id: number; kind: ToastKind; onDismiss: (id: number) => void }>) {
  const text = TOAST_TEXT[kind];
  return (
    <Toast
      onOpenChange={(open) => {
        if (!open) onDismiss(id);
      }}
    >
      <ToastTitle>{text.title}</ToastTitle>
      <ToastDescription>{text.description}</ToastDescription>
      <ToastAction altText={text.action} asChild>
        <Link to={text.to()}>{text.action}</Link>
      </ToastAction>
    </Toast>
  );
}
