import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { SCOREBOARD_SORTS, parseScoreboardSort, type ScoreboardSort } from "./scoreboard-list";

/** Name filter and sort selector for a participant scoreboard (#3001). */
export function ScoreboardControls({
  filter,
  sort,
  teamMode,
  onFilterChange,
  onSortChange,
}: Readonly<{
  filter: string;
  sort: ScoreboardSort;
  teamMode: boolean;
  onFilterChange: (value: string) => void;
  onSortChange: (value: ScoreboardSort) => void;
}>) {
  return (
    <>
      <div className="flex items-center gap-2">
        <Label htmlFor="scoreboard-filter" className="text-xs text-muted-foreground">
          {teamMode ? "Filter teams" : "Filter participants"}
        </Label>
        <Input
          id="scoreboard-filter"
          type="search"
          autoComplete="off"
          maxLength={100}
          className="h-8 w-[200px]"
          value={filter}
          onChange={(change) => onFilterChange(change.target.value)}
        />
      </div>
      <div className="flex items-center gap-2">
        <Label id="scoreboard-sort-label" className="text-xs text-muted-foreground">
          Sort by
        </Label>
        <Select value={sort} onValueChange={(value) => onSortChange(parseScoreboardSort(value))}>
          <SelectTrigger size="sm" className="w-[180px]" aria-labelledby="scoreboard-sort-label">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SCOREBOARD_SORTS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </>
  );
}
