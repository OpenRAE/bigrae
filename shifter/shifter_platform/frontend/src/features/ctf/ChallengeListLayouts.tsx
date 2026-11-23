/**
 * The card, list, and table layouts of one challenge group (#3012). Each layout
 * shows the same rows in the same order; only the presentation changes.
 */
import { Link, useLocation } from "react-router";

import { CheckCircle2 } from "lucide-react";

import type { CtfChallengeListItem } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { UNCATEGORIZED, type ChallengeLayout } from "./challenge-list";
import { titleCase } from "./format";
import { ctfChallengeDetailPath } from "./routes";

type Challenge = Readonly<{ challenge: CtfChallengeListItem }>;

function solvedText(challenge: CtfChallengeListItem): string | null {
  if (challenge.solved) return "Solved";
  return challenge.team_solved ? "Solved by your team" : null;
}

/** The link keeps the list query parameters, so the challenge page follows the shown order. */
function ChallengeLink({ challenge, className }: Challenge & Readonly<{ className?: string }>) {
  const { search } = useLocation();
  return (
    <Link to={{ pathname: ctfChallengeDetailPath(challenge.id), search }} className={className}>
      {challenge.name}
    </Link>
  );
}

function SolvedBadge({ challenge }: Challenge) {
  const text = solvedText(challenge);
  if (text === null) return null;
  return (
    <Badge variant="secondary" className="gap-1">
      <CheckCircle2 className="size-3" aria-hidden="true" />
      {text}
    </Badge>
  );
}

function ChallengeFacts({ challenge }: Challenge) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>{challenge.points} pts</span>
      {challenge.difficulty ? <span>· {titleCase(challenge.difficulty)}</span> : null}
    </div>
  );
}

/** The whole card is one link, so the name, badge, and facts are its accessible name. */
function ChallengeCard({ challenge }: Challenge) {
  const { search } = useLocation();
  return (
    <Link
      to={{ pathname: ctfChallengeDetailPath(challenge.id), search }}
      className="block rounded-lg border border-border/60 p-4 transition-colors hover:border-border hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">{challenge.name}</span>
        <SolvedBadge challenge={challenge} />
      </div>
      <div className="mt-2">
        <ChallengeFacts challenge={challenge} />
      </div>
    </Link>
  );
}

function CardsLayout({ items }: Readonly<{ items: readonly CtfChallengeListItem[] }>) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((challenge) => (
        <ChallengeCard key={challenge.id} challenge={challenge} />
      ))}
    </div>
  );
}

function ListLayout({ items, name }: Readonly<{ items: readonly CtfChallengeListItem[]; name: string }>) {
  return (
    <ul aria-label={name} className="divide-y divide-border/60 rounded-lg border border-border/60">
      {items.map((challenge) => (
        <li key={challenge.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <ChallengeLink
              challenge={challenge}
              className="font-medium break-words hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            />
            <ChallengeFacts challenge={challenge} />
          </div>
          <SolvedBadge challenge={challenge} />
        </li>
      ))}
    </ul>
  );
}

function TableLayout({ items, name }: Readonly<{ items: readonly CtfChallengeListItem[]; name: string }>) {
  return (
    <Table>
      <TableCaption className="sr-only">{name}</TableCaption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="col">Challenge</TableHead>
          <TableHead scope="col">Category</TableHead>
          <TableHead scope="col">Difficulty</TableHead>
          <TableHead scope="col">Points</TableHead>
          <TableHead scope="col">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((challenge) => (
          <TableRow key={challenge.id}>
            <TableCell className="min-w-[12rem] font-medium break-words whitespace-normal">
              <ChallengeLink
                challenge={challenge}
                className="hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              />
            </TableCell>
            <TableCell className="whitespace-normal">{titleCase(challenge.category || UNCATEGORIZED)}</TableCell>
            <TableCell>{challenge.difficulty ? titleCase(challenge.difficulty) : "—"}</TableCell>
            <TableCell>{challenge.points}</TableCell>
            <TableCell>{solvedText(challenge) ?? "Not solved"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Show one group of challenges in the selected layout. Only that layout is rendered. */
export function ChallengeGroupLayout({
  layout,
  items,
  name,
}: Readonly<{ layout: ChallengeLayout; items: readonly CtfChallengeListItem[]; name: string }>) {
  if (layout === "list") return <ListLayout items={items} name={name} />;
  if (layout === "table") return <TableLayout items={items} name={name} />;
  return <CardsLayout items={items} />;
}
