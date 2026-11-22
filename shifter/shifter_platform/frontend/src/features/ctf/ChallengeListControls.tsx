import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

import { CHALLENGE_SORTS, CHALLENGE_VIEWS, parseSort, type ChallengeSort, type ChallengeView } from "./challenge-list";

/** View toggle buttons and the sort selector for the participant challenge list. */
export function ChallengeListControls({
  view,
  sort,
  onViewChange,
  onSortChange,
}: Readonly<{
  view: ChallengeView;
  sort: ChallengeSort;
  onViewChange: (view: ChallengeView) => void;
  onSortChange: (sort: ChallengeSort) => void;
}>) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="View">
        {CHALLENGE_VIEWS.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={view === option.value ? "default" : "outline"}
            aria-pressed={view === option.value}
            onClick={() => onViewChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Label htmlFor="challenge-sort" className="text-xs text-muted-foreground">
          Sort within groups
        </Label>
        <select
          id="challenge-sort"
          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          value={sort}
          onChange={(change) => onSortChange(parseSort(change.target.value))}
        >
          {CHALLENGE_SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
