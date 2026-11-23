import { useCallback, useMemo } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { CheckCircle2 } from "lucide-react";

import { useCtfChallenges } from "@/api/ctf";
import type { CtfChallengeListItem } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { ChallengeListControls } from "./ChallengeListControls";
import { isSolved, readListView } from "./challenge-list";
import { titleCase } from "./format";
import { LabelFilterRow } from "./label-filters";
import { ctfChallengeDetailPath } from "./routes";

type ListParam = "view" | "sort" | "tag" | "topic";
const PARAM_DEFAULTS: Readonly<Record<ListParam, string | null>> = { view: "category", sort: "order", tag: null, topic: null };

/** List state held in the URL, so it stays when the participant opens a challenge and goes back. */
function useListParams() {
  const [params, setParams] = useSearchParams();
  const update = useCallback(
    (key: ListParam, value: string | null) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (value === null || value === PARAM_DEFAULTS[key]) next.delete(key);
          else next.set(key, value);
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  return { params, update };
}

/** The card link keeps the list query parameters, so the challenge page follows the shown order. */
function ChallengeCard({ challenge }: Readonly<{ challenge: CtfChallengeListItem }>) {
  const { search } = useLocation();
  return (
    <Link
      to={{ pathname: ctfChallengeDetailPath(challenge.id), search }}
      className="block rounded-lg border border-border/60 p-4 transition-colors hover:border-border hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">{challenge.name}</span>
        {isSolved(challenge) ? (
          <Badge variant="secondary" className="gap-1">
            <CheckCircle2 className="size-3" aria-hidden="true" />
            {challenge.solved ? "Solved" : "Solved by your team"}
          </Badge>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{challenge.points} pts</span>
        {challenge.difficulty ? <span>· {titleCase(challenge.difficulty)}</span> : null}
      </div>
    </Link>
  );
}

function ChallengesBody({ query }: Readonly<{ query: ReturnType<typeof useCtfChallenges> }>) {
  const { params, update } = useListParams();
  const { view, sort, tagLabels, topicLabels, activeTag, activeTopic, groups: grouped } = useMemo(
    () => readListView(query.data ?? [], params),
    [query.data, params],
  );

  if (query.isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <Skeleton key={row} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load challenges</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }

  const controls = (
    <div className="flex flex-col gap-2">
      <ChallengeListControls
        view={view}
        sort={sort}
        onViewChange={(value) => update("view", value)}
        onSortChange={(value) => update("sort", value)}
      />
      <LabelFilterRow
        axis="tags"
        labels={tagLabels}
        active={activeTag}
        onToggle={(value) => update("tag", activeTag === value ? null : value)}
      />
      <LabelFilterRow
        axis="topics"
        labels={topicLabels}
        active={activeTopic}
        onToggle={(value) => update("topic", activeTopic === value ? null : value)}
      />
    </div>
  );

  if (grouped.length === 0) {
    return (
      <div className="space-y-4">
        {controls}
        <Card>
          <CardContent className="grid place-items-center px-6 py-16 text-center">
            <p className="text-sm font-medium">
              {activeTag || activeTopic ? "No challenges match this filter" : "No challenges available yet"}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {activeTag || activeTopic
                ? "Clear the filter to see every available challenge."
                : "Challenges appear here once the event releases them."}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {controls}
      {grouped.map(({ key, label, items }) => (
        <section key={key} aria-label={label ?? "All challenges"}>
          {label === null ? null : <h2 className="mb-3 text-sm font-semibold">{titleCase(label)}</h2>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((challenge) => (
              <ChallengeCard key={challenge.id} challenge={challenge} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function ChallengesPage() {
  const query = useCtfChallenges();
  const total = query.data?.length ?? 0;
  const solved = query.data?.filter(isSolved).length ?? 0;

  return (
    <>
      <PageHeader
        title="Challenges"
        description={query.data ? `${solved} of ${total} solved` : "Browse available challenges"}
      />
      <ChallengesBody query={query} />
    </>
  );
}
