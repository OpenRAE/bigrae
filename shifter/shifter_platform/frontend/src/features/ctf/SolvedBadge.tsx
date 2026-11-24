import { CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { solvedLabel } from "./format";

type Solvable = Readonly<{ solved: boolean; team_solved: boolean; team_solved_by?: string | null }>;

/**
 * Solved marker for a challenge. A teammate's solve names the member, and a
 * display name can be long, so the badge shrinks and truncates the label. The
 * title keeps the full label available.
 */
export function SolvedBadge({ challenge }: Readonly<{ challenge: Solvable }>) {
  if (!challenge.solved && !challenge.team_solved) return null;
  const label = solvedLabel(challenge);
  return (
    <Badge variant="secondary" className="min-w-0 max-w-full shrink gap-1" title={label}>
      <CheckCircle2 className="size-3" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </Badge>
  );
}
