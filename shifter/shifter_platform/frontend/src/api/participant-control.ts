import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { components } from "./schema";

export type ControlCommand = components["schemas"]["ControlCommand"];
export type ControlState = components["schemas"]["ControlState"];
export type ControlSelection = components["schemas"]["ControlSelection"];
type ConfigurationRequest = components["schemas"]["ControlConfigurationRequest"];
type ConfigurationStatus = components["schemas"]["ControlConfigurationStatus"];
type ControlOptions = components["schemas"]["ControlOptions"];
type ControlOperation = components["schemas"]["ControlOperation"];

const base = "/participant-control";
const optionsKey = (participant: string) => ["participant-control-options", participant] as const;
const stateKey = (binding: string) => ["participant-control-state", binding] as const;
const sourceKey = (organization: string, source: string) => ["participant-control-source", organization, source] as const;
const sourcePath = (organization: string, source: string) =>
  `${base}/organizations/${encodeURIComponent(organization)}/sources/${encodeURIComponent(source)}/`;

export function useControlConfiguration(organization: string, source: string, enabled = true) {
  return useQuery({
    queryKey: sourceKey(organization, source), enabled: enabled && Boolean(organization && source), retry: false,
    queryFn: ({ signal }) => apiFetch<ConfigurationStatus>(sourcePath(organization, source), { signal }),
  });
}

export function useConfigureControl(organization: string, source: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ConfigurationRequest) => apiFetch<components["schemas"]["ControlConfiguration"]>(
      sourcePath(organization, source), { method: "POST", body },
    ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: sourceKey(organization, source) });
      await client.invalidateQueries({ queryKey: ["participant-control-options"] });
    },
  });
}

export function useControlOptions(participant: string, enabled = true) {
  return useQuery({
    queryKey: optionsKey(participant), enabled: enabled && Boolean(participant), retry: false,
    queryFn: ({ signal }) => apiFetch<ControlOptions>(
      `${base}/ctf/participants/${encodeURIComponent(participant)}/binding/`, { signal },
    ),
  });
}

export function useActivateControl(participant: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (configuration_id: string) => apiFetch<ControlState>(
      `${base}/ctf/participants/${encodeURIComponent(participant)}/binding/`,
      { method: "POST", body: { configuration_id } },
    ),
    onSuccess: async (state) => {
      client.setQueryData([...stateKey(state.binding_id), "latest"], state);
      await client.invalidateQueries({ queryKey: optionsKey(participant) });
    },
  });
}

export function useControlState(binding: string, before?: string) {
  return useQuery({
    queryKey: [...stateKey(binding), before ?? "latest"], enabled: Boolean(binding), retry: false,
    queryFn: ({ signal }) => apiFetch<ControlState>(`${base}/ctf/bindings/${encodeURIComponent(binding)}/${before ? `?before=${encodeURIComponent(before)}` : ""}`, { signal }),
    refetchInterval: (query) => ["pausing", "resuming"].includes(query.state.data?.range_status ?? "") ? 2_000 : false,
  });
}

export function useControlCommand(binding: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ControlCommand) => apiFetch<ControlOperation>(
      `${base}/ctf/bindings/${encodeURIComponent(binding)}/commands/`, { method: "POST", body },
    ),
    onSettled: () => client.invalidateQueries({ queryKey: stateKey(binding) }),
  });
}

export function useRetryControlCommand(binding: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (command: string) => apiFetch<ControlOperation>(
      `${base}/ctf/bindings/${encodeURIComponent(binding)}/commands/${encodeURIComponent(command)}/retry/`,
      { method: "POST", body: {} },
    ),
    onSettled: () => client.invalidateQueries({ queryKey: stateKey(binding) }),
  });
}
