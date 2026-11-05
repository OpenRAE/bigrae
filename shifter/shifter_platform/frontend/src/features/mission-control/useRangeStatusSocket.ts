/**
 * Live-projection hook for range status (#1370).
 *
 * Opens `ws(s)://<host>/ws/range-status/<request_id>/`
 * (`mission_control/routing.py` -> `RangeStatusConsumer`,
 * `mission_control/status_consumers.py`). The consumer hydrates on connect and
 * streams deltas, both framed identically:
 *
 *   { "type": "status", "request_id": "<uuid>", "status": "<ResourceStatus>", "error_message"?: string }
 *
 * Per the #1370 preflight guardrails, this socket is ADVISORY / live-projection
 * only, never authority: on any `status` message this hook invalidates the
 * `useCurrentRange` query so the canonical `/api/v1/mission-control/range/`
 * read re-fetches — it never stores range data itself, and a dead/unavailable
 * socket just leaves `useCurrentRange`'s bounded `refetchInterval` polling as
 * the fallback (which already runs whenever the range is in a transient
 * status; see `api/mission-control.ts`).
 *
 * Reconnects through `openReconnectingSocket` (`@/lib/reconnectingSocket`):
 * bounded exponential backoff with equal jitter, and no retry on NORMAL,
 * NOT_AUTHENTICATED, or PERMISSION_DENIED close codes.
 */
import { useEffect, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { missionControlKeys } from "@/api/mission-control";
import { openReconnectingSocket, sameOriginSocketUrl } from "@/lib/reconnectingSocket";

export interface RangeStatusSocket {
  /** Advisory connectivity indicator for a small live/offline affordance. */
  readonly connected: boolean;
}

/** No-op when `requestId` is null (no active range to watch). */
export function useRangeStatusSocket(requestId: string | null): RangeStatusSocket {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!requestId) {
      setConnected(false);
      return;
    }
    return openReconnectingSocket(sameOriginSocketUrl(`/ws/range-status/${requestId}/`), {
      onConnectedChange: setConnected,
      onMessage: (data) => {
        let message: { type?: string } | null = null;
        try {
          message = JSON.parse(data) as { type?: string };
        } catch {
          return; // Malformed frame; the polling fallback still covers us.
        }
        if (message?.type === "status") {
          queryClient.invalidateQueries({ queryKey: missionControlKeys.currentRange });
        }
      },
    });
  }, [requestId, queryClient]);

  return { connected };
}
