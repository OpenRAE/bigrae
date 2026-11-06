import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { Loader2 } from "lucide-react";

import { ModelSourcePicker } from "@/components/ModelSourcePicker";
import type { ModelSourceSelection } from "@/api/model-sources";

import { describeMutationError } from "@/api/errors";
import { useAgents, useLaunchRange, useLaunchWorkspaces, useScenarios } from "@/api/mission-control";
import type { AgentListItem, ScenarioListItem } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

import { missionControlDashboardPath, missionControlHistoryPath } from "./routes";

interface FormErrors {
  scenario?: string;
  agent?: string;
}

/** Require a scenario and any agent upload that its contract needs. */
function validateLaunchForm(scenarioId: string, agentId: string, requiresAgent: boolean): FormErrors {
  const errors: FormErrors = {};
  if (!scenarioId) errors.scenario = "Select a scenario to launch.";
  if (requiresAgent && !agentId) errors.agent = "Select an agent to launch.";
  return errors;
}

function FieldError({ id, message }: Readonly<{ id: string; message?: string }>) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

/** Only an explicit no-agent contract permits launch without an upload. */
function needsAgent(scenario: ScenarioListItem | undefined): boolean {
  const requirements = scenario?.agent_requirements;
  return !(requirements?.requires_windows === false
    && requirements.requires_linux === false
    && requirements.has_from_agent === false);
}

interface LaunchOptionsFormProps {
  scenarioList: readonly ScenarioListItem[];
  agentList: readonly AgentListItem[];
  scenarioId: string;
  onScenarioIdChange: (value: string) => void;
  agentId: string;
  onAgentIdChange: (value: string) => void;
  errors: FormErrors;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
  isPending: boolean;
  modelSources: ModelSourceSelection;
  onModelSourcesChange: (value: ModelSourceSelection) => void;
  workspace: string;
}

/** The scenario/agent picker form, once options have loaded successfully. */
function LaunchOptionsForm({
  scenarioList,
  agentList,
  scenarioId,
  onScenarioIdChange,
  agentId,
  onAgentIdChange,
  errors,
  onSubmit,
  onCancel,
  isPending, modelSources, onModelSourcesChange, workspace,
}: Readonly<LaunchOptionsFormProps>) {
  const selectedScenario = scenarioList.find((scenario) => scenario.id === scenarioId);

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card>
        <CardContent className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="f-scenario">Scenario</Label>
            <Select value={scenarioId} onValueChange={onScenarioIdChange}>
              <SelectTrigger
                id="f-scenario"
                className="w-full"
                aria-invalid={errors.scenario ? true : undefined}
                aria-describedby={errors.scenario ? "f-scenario-e" : undefined}
              >
                <SelectValue placeholder="Select a scenario" />
              </SelectTrigger>
              <SelectContent>
                {scenarioList.map((scenario) => (
                  <SelectItem key={scenario.id} value={scenario.id}>
                    {scenario.name || scenario.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedScenario?.description ? (
              <p className="text-sm text-muted-foreground">{selectedScenario.description}</p>
            ) : null}
            <FieldError id="f-scenario-e" message={errors.scenario} />
          </div>

          {needsAgent(selectedScenario) ? <div className="flex flex-col gap-2">
            <Label htmlFor="f-agent">Agent</Label>
            <Select value={agentId} onValueChange={onAgentIdChange}>
              <SelectTrigger
                id="f-agent"
                className="w-full"
                aria-invalid={errors.agent ? true : undefined}
                aria-describedby={errors.agent ? "f-agent-e" : undefined}
              >
                <SelectValue placeholder="Select an agent" />
              </SelectTrigger>
              <SelectContent>
                {agentList.map((agent) => (
                  <SelectItem key={agent.id} value={String(agent.id)}>
                    {agent.name} ({agent.os_name})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="f-agent-e" message={errors.agent} />
          </div> : null}
          <ModelSourcePicker scenario={scenarioId} workspace={workspace} value={modelSources} onChange={onModelSourcesChange} disabled={isPending} />
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
            {isPending ? "Launching…" : "Launch range"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}

interface LaunchOptionsSectionProps extends LaunchOptionsFormProps {
  optionsError: boolean;
  optionsLoading: boolean;
}

/** Loading skeleton, load-failure alert, or the launch form — never more than one at a time. */
function LaunchOptionsSection({ optionsError, optionsLoading, ...formProps }: Readonly<LaunchOptionsSectionProps>) {
  if (optionsError) {
    return (
      <div className="space-y-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load launch options</AlertTitle>
          <AlertDescription>Select another workspace or retry.</AlertDescription>
        </Alert>
        <LaunchOptionsForm {...formProps} />
      </div>
    );
  }

  if (optionsLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-40" />
      </div>
    );
  }

  return <LaunchOptionsForm {...formProps} />;
}

/** Launch an authorized scenario in the selected workspace. */
export function RangeLaunchPage() {
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState("");
  const launchWorkspaces = useLaunchWorkspaces();
  const scenarios = useScenarios(workspace);
  const agents = useAgents(workspace);
  const launch = useLaunchRange();

  const [scenarioId, setScenarioId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [modelSources, setModelSources] = useState<ModelSourceSelection>({ aliases: [] });

  const scenarioList = scenarios.data?.scenarios ?? [];
  const agentList = agents.data?.agents ?? [];

  const optionsLoading = scenarios.isLoading || agents.isLoading;
  const optionsError = scenarios.isError || agents.isError;

  const serverError = describeMutationError(launch.error, "The range could not be launched.");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const requiresAgent = needsAgent(scenarioList.find((scenario) => scenario.id === scenarioId));
    const nextErrors = validateLaunchForm(scenarioId, agentId, requiresAgent);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    launch.mutate(
      { scenario: scenarioId, ...(requiresAgent ? { agent_id: Number(agentId) } : { agents: {} }), ...(workspace ? { workspace_uuid: workspace } : {}), ...(modelSources.aliases.length ? { model_sources: modelSources } : {}) },
      { onSuccess: () => navigate(missionControlDashboardPath()) },
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={missionControlHistoryPath()}>
          Ranges
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">Launch</span>
      </nav>

      <PageHeader title="Launch a range" description="Choose a workspace and a scenario to start a range." />

      {serverError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not launch this range</AlertTitle>
          <AlertDescription>{serverError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mb-5 flex flex-col gap-2">
        <Label htmlFor="f-workspace">Workspace</Label>
        {launchWorkspaces.isLoading ? <Skeleton className="h-9 w-full" /> : null}
        {launchWorkspaces.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not load launch workspaces</AlertTitle>
            <AlertDescription>Retry before choosing where to launch this range.</AlertDescription>
          </Alert>
        ) : null}
        {launchWorkspaces.data ? (
          <select
            id="f-workspace"
            className="w-full rounded border bg-background p-2"
            value={workspace}
            onChange={(event) => {
              setWorkspace(event.target.value);
              setScenarioId("");
              setAgentId("");
              setModelSources({ aliases: [] });
            }}
          >
            {launchWorkspaces.data.personal_available ? <option value="">Personal workspace</option> : null}
            {launchWorkspaces.data.workspaces.map((item) => (
              <option key={item.uuid} value={item.uuid}>{item.organization_name} / {item.name}</option>
            ))}
          </select>
        ) : null}
        {launchWorkspaces.hasNextPage ? <Button type="button" disabled={launchWorkspaces.isFetchingNextPage} onClick={() => launchWorkspaces.fetchNextPage()}>Load more workspaces</Button> : null}
      </div>

      <LaunchOptionsSection
        optionsError={optionsError}
        optionsLoading={optionsLoading}
        scenarioList={scenarioList}
        agentList={agentList}
        scenarioId={scenarioId}
        onScenarioIdChange={(value) => { setScenarioId(value); setModelSources({ aliases: [] }); }}
        agentId={agentId}
        onAgentIdChange={setAgentId}
        errors={errors}
        onSubmit={onSubmit}
        onCancel={() => navigate(missionControlDashboardPath())}
        isPending={launch.isPending}
        modelSources={modelSources} onModelSourcesChange={setModelSources}
        workspace={workspace}
      />
    </div>
  );
}
