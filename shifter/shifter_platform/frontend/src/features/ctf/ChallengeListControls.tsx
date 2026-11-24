import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

import {
  CHALLENGE_LAYOUTS,
  CHALLENGE_SORTS,
  CHALLENGE_VIEWS,
  parseSort,
  type ChallengeLayout,
  type ChallengeSort,
  type ChallengeView,
} from "./challenge-list";

/** A named group of toggle buttons; the selected option has `aria-pressed`. */
function ToggleGroup<T extends string>({
  legend,
  options,
  value,
  onChange,
}: Readonly<{
  legend: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}>) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-wrap items-center gap-1.5 border-0 p-0">
      <legend className="sr-only">{legend}</legend>
      {options.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant={value === option.value ? "default" : "outline"}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </fieldset>
  );
}

/** View and layout toggle buttons and the sort selector for the participant challenge list. */
export function ChallengeListControls({
  view,
  sort,
  layout,
  onViewChange,
  onSortChange,
  onLayoutChange,
}: Readonly<{
  view: ChallengeView;
  sort: ChallengeSort;
  layout: ChallengeLayout;
  onViewChange: (view: ChallengeView) => void;
  onSortChange: (sort: ChallengeSort) => void;
  onLayoutChange: (layout: ChallengeLayout) => void;
}>) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup legend="View" options={CHALLENGE_VIEWS} value={view} onChange={onViewChange} />
        <ToggleGroup legend="Layout" options={CHALLENGE_LAYOUTS} value={layout} onChange={onLayoutChange} />
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
