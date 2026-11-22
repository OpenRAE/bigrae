import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn().mockResolvedValue({}) }));

import { ctfKeys, useJoinTeam, useLeaveTeam } from "./ctf";

function wrapper(client: QueryClient) {
  function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

async function expectChallengeListStale(client: QueryClient, mutate: () => Promise<unknown>) {
  await act(async () => {
    await mutate();
  });
  await waitFor(() => expect(client.getQueryState(ctfKeys.challenges())?.isInvalidated).toBe(true));
}

function seededClient(): QueryClient {
  const client = new QueryClient();
  client.setQueryData(ctfKeys.challenges(), []);
  return client;
}

describe("team membership changes refresh team solve state (#2998)", () => {
  it("marks the challenge list stale after joining a team", async () => {
    const client = seededClient();
    const { result } = renderHook(() => useJoinTeam(), { wrapper: wrapper(client) });
    await expectChallengeListStale(client, () => result.current.mutateAsync({ invite_code: "synthetic-code" }));
  });

  it("marks the challenge list stale after leaving a team", async () => {
    const client = seededClient();
    const { result } = renderHook(() => useLeaveTeam(), { wrapper: wrapper(client) });
    await expectChallengeListStale(client, () => result.current.mutateAsync({}));
  });
});
