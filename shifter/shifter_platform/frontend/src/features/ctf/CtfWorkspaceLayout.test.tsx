import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen } from "@testing-library/react";

import { FakeWebSocket, installFakeWebSocket } from "@/test/fake-websocket";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { CtfWorkspaceLayout } from "./CtfWorkspaceLayout";

const mockApi = vi.mocked(apiFetch);

const ALL_KINDS = ["messages", "challenge_released", "first_blood", "position_changed", "range_ready"];
let liveKinds: string[] = ALL_KINDS;
const currentEvent = () => ({
  event: { id: "e1", name: "Spring CTF", status: "active", live_notifications: liveKinds },
  participant: { id: "p1", name: "Alice", status: "active" },
});
const INBOX = "/ctf/me/events/e1/communications/";
let actionRequired = 0;

let restoreWebSocket: () => void;

beforeEach(() => {
  actionRequired = 0;
  liveKinds = ALL_KINDS;
  mockApi.mockReset();
  mockApi.mockImplementation(async (path: string) => {
    if (path === INBOX) {
      return {
        results: [],
        next_offset: null,
        unread_count: actionRequired,
        action_required_count: actionRequired,
        allowed_link_hosts: [],
      };
    }
    if (path.endsWith("/me/event/")) return currentEvent();
    return { images: [], announcements: [] };
  });
  restoreWebSocket = installFakeWebSocket();
});

afterEach(() => {
  restoreWebSocket();
});

const inboxCalls = () => mockApi.mock.calls.filter(([path]) => path === INBOX);
const frame = (payload: unknown, topic = "ctf:event:e1") =>
  ({ data: JSON.stringify({ type: "notification", id: 7, event_id: "s1", topic, payload }) }) as MessageEvent;

async function openSocket() {
  renderRoute(<CtfWorkspaceLayout />);
  await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  await vi.waitFor(() => expect(inboxCalls()).toHaveLength(1));
  const socket = FakeWebSocket.instances[0];
  act(() => socket.emitOpen());
  return socket;
}

describe("CtfWorkspaceLayout", () => {
  it("treats a communication wake-up as a refetch hint, never as a read", async () => {
    const socket = await openSocket();
    expect(socket.url).toContain("/ws/notifications/");
    expect(socket.sent[0]).toContain("ctf:event:e1");

    act(() =>
      socket.onmessage?.(
        frame({
          kind: "communication",
          snapshot_id: "3f2c3f7e-1d2b-4a5c-9e8f-0a1b2c3d4e5f",
          intent_id: "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
        }),
      ),
    );

    expect(await screen.findByText("New message")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open inbox" })).toHaveAttribute("href", "/ctf/inbox/");
    await vi.waitFor(() => expect(inboxCalls()).toHaveLength(2));
    // The socket frame carries references only; nothing is posted on its behalf.
    expect(mockApi.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  });

  it("refetches on refresh hints and drops malformed or foreign frames silently", async () => {
    const socket = await openSocket();

    act(() => socket.onmessage?.(frame({ kind: "refresh" })));
    await vi.waitFor(() => expect(inboxCalls()).toHaveLength(2));
    expect(screen.queryByText("New message")).not.toBeInTheDocument();

    act(() => socket.onmessage?.({ data: "not-json" } as MessageEvent));
    act(() => socket.onmessage?.(frame({ kind: "communication", snapshot_id: "x" })));
    act(() => socket.onmessage?.(frame({ kind: "refresh" }, "ctf:event:other")));
    // A legacy content-bearing frame is never rendered as content.
    act(() => socket.onmessage?.(frame({ kind: "first_blood", participant_name: "<b>Bob</b>" })));
    expect(screen.queryByText("New message")).not.toBeInTheDocument();
    expect(screen.queryByText(/Bob/)).not.toBeInTheDocument();
    expect(inboxCalls()).toHaveLength(2);
  });

  it.each(["null", "5", "true", '"notification"', "[]"])(
    "ignores JSON value %s without refetching or rendering content",
    async (data) => {
      const socket = await openSocket();

      await act(async () => socket.onmessage?.({ data } as MessageEvent));

      expect(inboxCalls()).toHaveLength(1);
      expect(screen.queryByText("New message")).not.toBeInTheDocument();
      expect(screen.queryByText("First blood!")).not.toBeInTheDocument();
    },
  );

  it("opens no socket when the event selects no live notification kinds", async () => {
    liveKinds = [];
    renderRoute(<CtfWorkspaceLayout />);

    await vi.waitFor(() => expect(inboxCalls()).toHaveLength(1));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("shows fixed-text toasts for position and range hints", async () => {
    const socket = await openSocket();

    act(() => socket.onmessage?.(frame({ kind: "position_changed", rank: 1, name: "<b>Bob</b>" })));
    expect(await screen.findByText("Scoreboard position changed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open scoreboard" })).toHaveAttribute("href", "/ctf/scoreboard/");
    expect(screen.queryByText(/Bob/)).not.toBeInTheDocument();

    act(() => socket.onmessage?.(frame({ kind: "range_ready" })));
    expect(await screen.findByText("Range ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open range" })).toHaveAttribute("href", "/ctf/range/");
    // A hint carries no read; nothing is posted on its behalf.
    expect(mockApi.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  });

  it("reconnects and resubscribes after a dropped socket, and stops on an authorization close", async () => {
    const socket = await openSocket();

    act(() => socket.emitClose(1006));
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2), { timeout: 2000 });
    const second = FakeWebSocket.instances[1];
    act(() => second.emitOpen());
    expect(second.sent[0]).toContain("ctf:event:e1");

    act(() => second.emitClose(4003));
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("announces open obligations without moving focus or blocking navigation", async () => {
    actionRequired = 2;
    renderRoute(<CtfWorkspaceLayout />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("2 messages need your action.");
    expect(screen.getByRole("link", { name: "Review messages" })).toHaveAttribute(
      "href",
      "/ctf/inbox/?view=action_required",
    );
    expect(document.activeElement).toBe(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
