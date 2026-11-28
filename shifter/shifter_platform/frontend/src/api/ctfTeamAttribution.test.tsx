import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("./client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "./client";
import { ctfKeys, useJoinTeam, useLeaveTeam, useUpdateCtfProfile } from "./ctf";

const mockApi = vi.mocked(apiFetch);

// Team membership and display names change the team solve attribution on the
// challenge list and detail, so these mutations must refresh both reads.
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(ctfKeys.challenges(), []);
  client.setQueryData(ctfKeys.challenge("c1"), {});
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

function invalidated(client: QueryClient) {
  return {
    list: client.getQueryState(ctfKeys.challenges())?.isInvalidated,
    detail: client.getQueryState(ctfKeys.challenge("c1"))?.isInvalidated,
  };
}

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockResolvedValue({});
});

describe("team solve attribution freshness", () => {
  it("refreshes the challenge list and detail after joining a team", async () => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useJoinTeam(), { wrapper });
    await act(() => result.current.mutateAsync({ invite_code: "CODE" }));
    expect(invalidated(client)).toEqual({ list: true, detail: true });
  });

  it("refreshes the challenge list and detail after leaving a team", async () => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useLeaveTeam(), { wrapper });
    await act(() => result.current.mutateAsync({}));
    expect(invalidated(client)).toEqual({ list: true, detail: true });
  });

  it("refreshes the challenge list and detail after a profile update", async () => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useUpdateCtfProfile(), { wrapper });
    await act(() => result.current.mutateAsync({}));
    expect(invalidated(client)).toEqual({ list: true, detail: true });
  });
});
