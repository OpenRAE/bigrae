import type { ReactNode } from "react";
import { QueryClientProvider, focusManager, onlineManager, type QueryClient } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "./client";
import { useCtfOrganizerScoreboard, useCtfScoreboard } from "./ctf";
import { ApiError } from "./errors";
import { createQueryClient } from "./queryClient";

const mockApi = vi.mocked(apiFetch);

// CTF-401: a scoring event shows within 30 seconds. The poll must leave
// headroom for the request and the render inside that budget.
const FRESHNESS_BUDGET_MS = 30_000;
const REQUEST_ALLOWANCE_MS = 5_000;

const BEFORE = { rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 1 }] };
const AFTER = { rankings: [{ rank: 1, participant_id: "p2", name: "Bob", score: 200, solve_count: 2 }] };

const BOARDS = [
  {
    board: "participant",
    path: "/ctf/events/e1/scoreboard/",
    useBoard: (enabled: boolean) => useCtfScoreboard("e1", "b1", enabled),
  },
  {
    board: "organizer",
    path: "/ctf/events/e1/organizer-scoreboard/",
    useBoard: (enabled: boolean) => useCtfOrganizerScoreboard("e1", "b1", enabled),
  },
];

let client: QueryClient;

function wrapper({ children }: Readonly<{ children: ReactNode }>) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Advance fake time and let the resulting fetches settle. */
async function elapse(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  // The production client: its global defaults turn focus refetch off.
  client = createQueryClient();
  mockApi.mockReset();
});

afterEach(() => {
  client.clear();
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
  vi.useRealTimers();
});

describe.each(BOARDS)("$board scoreboard refresh (#576)", ({ path, useBoard }) => {
  it("shows another participant's solve within 30 seconds without a reload", async () => {
    mockApi.mockResolvedValueOnce(BEFORE).mockResolvedValue(AFTER);
    const { result } = renderHook(() => useBoard(true), { wrapper });
    await elapse(0);
    expect(result.current.data).toEqual(BEFORE);

    await elapse(FRESHNESS_BUDGET_MS - REQUEST_ALLOWANCE_MS);

    expect(result.current.data).toEqual(AFTER);
    for (const [calledPath, options] of mockApi.mock.calls) {
      expect(calledPath).toBe(path);
      expect(options?.query).toEqual({ bracket: "b1" });
    }
  });

  it("polls only while an enabled read is mounted", async () => {
    mockApi.mockResolvedValue(BEFORE);
    renderHook(() => useBoard(false), { wrapper });
    await elapse(FRESHNESS_BUDGET_MS * 2);
    expect(mockApi).not.toHaveBeenCalled();

    const { unmount } = renderHook(() => useBoard(true), { wrapper });
    await elapse(FRESHNESS_BUDGET_MS);
    const polled = mockApi.mock.calls.length;
    expect(polled).toBeGreaterThan(1);

    unmount();
    await elapse(FRESHNESS_BUDGET_MS * 2);
    expect(mockApi).toHaveBeenCalledTimes(polled);
  });

  it("keeps polling through an outage and recovers when the server returns", async () => {
    let outage = false;
    mockApi.mockResolvedValueOnce(BEFORE).mockImplementation(async () => {
      if (outage) throw new ApiError(503, { code: "unavailable", message: "Unavailable" });
      return AFTER;
    });
    const { result } = renderHook(() => useBoard(true), { wrapper });
    await elapse(0);

    outage = true;
    await elapse(FRESHNESS_BUDGET_MS - REQUEST_ALLOWANCE_MS);
    expect(result.current.isError).toBe(true);

    outage = false;
    await elapse(FRESHNESS_BUDGET_MS - REQUEST_ALLOWANCE_MS);
    expect(result.current.isError).toBe(false);
    expect(result.current.data).toEqual(AFTER);
  });

  it("pauses in a background tab and reads the board again on return", async () => {
    mockApi.mockResolvedValueOnce(BEFORE).mockResolvedValue(AFTER);
    const { result } = renderHook(() => useBoard(true), { wrapper });
    await elapse(0);

    act(() => focusManager.setFocused(false));
    await elapse(FRESHNESS_BUDGET_MS * 2);
    expect(mockApi).toHaveBeenCalledTimes(1);

    act(() => focusManager.setFocused(true));
    await elapse(0);
    expect(mockApi).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual(AFTER);
  });

  it("reads the board again on reconnect", async () => {
    mockApi.mockResolvedValueOnce(BEFORE).mockResolvedValue(AFTER);
    const { result } = renderHook(() => useBoard(true), { wrapper });
    await elapse(0);

    act(() => onlineManager.setOnline(false));
    await elapse(FRESHNESS_BUDGET_MS * 2);
    expect(mockApi).toHaveBeenCalledTimes(1);

    act(() => onlineManager.setOnline(true));
    await elapse(0);
    expect(mockApi).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual(AFTER);
  });
});
