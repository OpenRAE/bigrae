import { useMemo, useState } from "react";

import { useCtfCurrentEvent, useCtfScoreboard } from "@/api/ctf";
import { ApiError } from "@/api/errors";
import type { CtfScoreboard, CtfScoreboardKind } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { ScoreboardControls } from "./ScoreboardControls";
import { rankingKey, rankingNumber, rankingString } from "./format";
import { ScoreboardGraph } from "./ScoreProgressionChart";
import { filterScoreboardRows, sortScoreboardRows, type ScoreboardSort } from "./scoreboard-list";

const ALL = "all";

/** Page header for each board; `default` is the event's own board (#2968). */
const HEADERS: Record<CtfScoreboardKind | "default", { title: string; description: string }> = {
  default: { title: "Scoreboard", description: "Event rankings" },
  individual: {
    title: "Individual scoreboard",
    description: "Participant rankings",
  },
  team: { title: "Team scoreboard", description: "Team rankings" },
};

function EmptyBoard({ title, detail }: Readonly<{ title: string; detail: string }>) {
  return (
    <div className="grid place-items-center px-6 py-16 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  );
}

function ScoreboardTable({ rows, teamMode }: Readonly<{ rows: Record<string, unknown>[]; teamMode: boolean }>) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-[70px]">Rank</TableHead>
          <TableHead>{teamMode ? "Team" : "Name"}</TableHead>
          <TableHead className="w-[100px]">Score</TableHead>
          <TableHead className="w-[100px]">Solves</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={rankingKey(row, index)}>
            {/* The server rank only: a sorted or filtered position is not a rank. */}
            <TableCell className="font-medium">{rankingNumber(row, "rank") ?? "—"}</TableCell>
            <TableCell>{rankingString(row, "name")}</TableCell>
            <TableCell>{rankingNumber(row, "score") ?? 0}</TableCell>
            <TableCell>{rankingNumber(row, "solve_count") ?? 0}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BracketSelect({
  brackets,
  bracket,
  onBracketChange,
}: Readonly<{
  brackets: NonNullable<CtfScoreboard["brackets"]>;
  bracket: string;
  onBracketChange: (value: string) => void;
}>) {
  return (
    <Select value={bracket} onValueChange={onBracketChange}>
      <SelectTrigger size="sm" className="w-[180px]" aria-label="Filter by bracket">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All brackets</SelectItem>
        {brackets.map((entry) => (
          <SelectItem key={entry.id} value={entry.id}>
            {entry.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

interface BoardControls {
  bracket: string;
  sort: ScoreboardSort;
  filter: string;
  onBracketChange: (value: string) => void;
  onSortChange: (value: ScoreboardSort) => void;
  onFilterChange: (value: string) => void;
}

function ScoreboardContent({
  data,
  kind,
  controls,
}: Readonly<{
  data: CtfScoreboard;
  kind?: CtfScoreboardKind;
  controls: BoardControls;
}>) {
  const { bracket, sort, filter } = controls;
  const source = bracket === ALL ? data.rankings : data.bracket_rankings;
  const rows = useMemo(
    () => sortScoreboardRows(filterScoreboardRows(source ?? [], filter), sort),
    [source, filter, sort],
  );

  if (data.scoreboard_hidden) {
    return (
      <Alert>
        <AlertTitle>Scoreboard hidden</AlertTitle>
        <AlertDescription>The organizer has hidden the scoreboard for this event.</AlertDescription>
      </Alert>
    );
  }

  const brackets = data.brackets ?? [];
  const teamMode = kind ? kind === "team" : Boolean(data.team_mode);
  let table: React.ReactNode;
  if (rows.length > 0) table = <ScoreboardTable rows={rows} teamMode={teamMode} />;
  else if ((source ?? []).length > 0) {
    table = <EmptyBoard title="No entries match this filter" detail="Clear the filter to see every entry." />;
  } else table = <EmptyBoard title="No scores yet" detail="Rankings appear once participants start solving." />;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {data.frozen ? <Badge variant="secondary">Frozen</Badge> : null}
        {brackets.length > 0 ? (
          <BracketSelect brackets={brackets} bracket={bracket} onBracketChange={controls.onBracketChange} />
        ) : null}
        <ScoreboardControls
          filter={filter}
          sort={sort}
          teamMode={teamMode}
          onFilterChange={controls.onFilterChange}
          onSortChange={controls.onSortChange}
        />
      </div>
      {(source ?? []).length > 0 ? (
        <ScoreboardGraph progression={data.progression} teamMode={teamMode} frozen={Boolean(data.frozen)} />
      ) : null}
      <Card className="overflow-hidden py-0">{table}</Card>
    </>
  );
}

/**
 * One board of one event. Its key is the event and the board kind, so a new
 * event or board starts with fresh bracket, sort, and filter state (#3001).
 * The state lives here, above the loading state, so a bracket reload keeps it.
 */
function ScoreboardBoard({ eventId, kind }: Readonly<{ eventId: string; kind?: CtfScoreboardKind }>) {
  const [bracket, setBracket] = useState<string>(ALL);
  const [sort, setSort] = useState<ScoreboardSort>("rank");
  const [filter, setFilter] = useState("");
  const scoreboard = useCtfScoreboard(eventId, bracket === ALL ? undefined : bracket, true, kind);

  if (scoreboard.isLoading) return <Skeleton className="h-64 w-full" />;
  if (scoreboard.isError || !scoreboard.data) return <LoadError />;
  const controls: BoardControls = {
    bracket,
    sort,
    filter,
    onBracketChange: setBracket,
    onSortChange: setSort,
    onFilterChange: setFilter,
  };
  return <ScoreboardContent data={scoreboard.data} kind={kind} controls={controls} />;
}

function LoadError() {
  return (
    <Alert variant="destructive">
      <AlertTitle>Could not load the scoreboard</AlertTitle>
      <AlertDescription>Please retry.</AlertDescription>
    </Alert>
  );
}

/**
 * Participant scoreboard. Without `kind` it shows the event's default board;
 * with `kind` it shows that board (#2968). A solo event has no team board.
 */
export function ScoreboardPage({ kind }: Readonly<{ kind?: CtfScoreboardKind }>) {
  const eventQuery = useCtfCurrentEvent();
  const eventId = eventQuery.data?.event.id ?? "";
  const noTeamBoard = kind === "team" && eventQuery.isSuccess && !eventQuery.data.event.team_mode;

  let body: React.ReactNode;
  if (eventQuery.error instanceof ApiError && eventQuery.error.status === 404) {
    body = (
      <Alert>
        <AlertTitle>No active event</AlertTitle>
        <AlertDescription>Join an event to see its scoreboard.</AlertDescription>
      </Alert>
    );
  } else if (noTeamBoard) {
    body = (
      <Alert>
        <AlertTitle>No team scoreboard</AlertTitle>
        <AlertDescription>This event does not use teams.</AlertDescription>
      </Alert>
    );
  } else if (eventQuery.isLoading) {
    body = <Skeleton className="h-64 w-full" />;
  } else if (eventQuery.isError || !eventId) {
    body = <LoadError />;
  } else {
    body = <ScoreboardBoard key={`${eventId}:${kind ?? "default"}`} eventId={eventId} kind={kind} />;
  }

  return (
    <>
      <PageHeader {...HEADERS[kind ?? "default"]} />
      {body}
    </>
  );
}
