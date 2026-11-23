/**
 * Browser-side views of the participant challenge list (#2998). The list API
 * stays the disclosure boundary: these functions only reorder and group the
 * rows it returned, and never change their input arrays.
 */
import { distinctLabels, filterByLabels, type Labeled } from "./label-filters";

export const CHALLENGE_VIEWS = [
  { value: "category", label: "By category" },
  { value: "status", label: "By status" },
  { value: "all", label: "All" },
] as const;

export const CHALLENGE_SORTS = [
  { value: "order", label: "Event order" },
  { value: "name", label: "Name" },
  { value: "points-asc", label: "Points, low to high" },
  { value: "points-desc", label: "Points, high to low" },
  { value: "difficulty", label: "Difficulty" },
] as const;

/** Presentation of each group (#3012). It never changes the rows or their order. */
export const CHALLENGE_LAYOUTS = [
  { value: "cards", label: "Cards" },
  { value: "list", label: "List" },
  { value: "table", label: "Table" },
] as const;

export type ChallengeView = (typeof CHALLENGE_VIEWS)[number]["value"];
export type ChallengeSort = (typeof CHALLENGE_SORTS)[number]["value"];
export type ChallengeLayout = (typeof CHALLENGE_LAYOUTS)[number]["value"];

export interface ListedChallenge {
  id: string;
  name: string;
  category: string;
  points: number;
  difficulty: string;
  order: number;
  solved: boolean;
  team_solved: boolean;
}

export interface ChallengeGroup<T> {
  key: string;
  /** Group heading, or null for the single unlabeled list. */
  label: string | null;
  items: T[];
}

/** Group and table label for a challenge with no category. */
export const UNCATEGORIZED = "Uncategorized";
const MISSION_CATEGORY = /^Mission\s+(\d+)\b/i;
const START_HERE_CATEGORY = /^Start Here$/i;
/** Domain order of `ctf.enums.ChallengeDifficulty`; other values sort after it. */
const DIFFICULTY_RANK: Readonly<Record<string, number>> = { easy: 0, medium: 1, hard: 2, expert: 3 };

/** Return the allowlisted view, or the default for a missing or unknown value. */
export function parseView(value: string | null): ChallengeView {
  return CHALLENGE_VIEWS.find((view) => view.value === value)?.value ?? "category";
}

/** Return the allowlisted sort, or the default for a missing or unknown value. */
export function parseSort(value: string | null): ChallengeSort {
  return CHALLENGE_SORTS.find((sort) => sort.value === value)?.value ?? "order";
}

/** Return the allowlisted layout, or cards for a missing or unknown value. */
export function parseLayout(value: string | null): ChallengeLayout {
  return CHALLENGE_LAYOUTS.find((layout) => layout.value === value)?.value ?? "cards";
}

/** One solve predicate for grouping and totals: a personal or a team solve. */
export function isSolved(challenge: Pick<ListedChallenge, "solved" | "team_solved">): boolean {
  return challenge.solved || challenge.team_solved;
}

type Compare = (left: ListedChallenge, right: ListedChallenge) => number;

const byOrder: Compare = (left, right) => left.order - right.order;
const byName: Compare = (left, right) => left.name.localeCompare(right.name);
const byId: Compare = (left, right) => (left.id < right.id ? -1 : Number(left.id > right.id));
const difficultyRank = (value: string) => DIFFICULTY_RANK[value] ?? Object.keys(DIFFICULTY_RANK).length;

const PRIMARY: Readonly<Record<ChallengeSort, Compare[]>> = {
  order: [byOrder, byName],
  name: [byName, byOrder],
  "points-asc": [(left, right) => left.points - right.points, byOrder, byName],
  "points-desc": [(left, right) => right.points - left.points, byOrder, byName],
  difficulty: [(left, right) => difficultyRank(left.difficulty) - difficultyRank(right.difficulty), byOrder, byName],
};

/** Return a sorted copy; full ties end with the challenge ID, so the order is deterministic. */
export function sortChallenges<T extends ListedChallenge>(items: readonly T[], sort: ChallengeSort): T[] {
  const compares = [...PRIMARY[sort], byId];
  return [...items].sort((left, right) => {
    for (const compare of compares) {
      const result = compare(left, right);
      if (result !== 0) return result;
    }
    return 0;
  });
}

function compareCategories(left: string, right: string): number {
  const leftStart = START_HERE_CATEGORY.test(left);
  const rightStart = START_HERE_CATEGORY.test(right);
  if (leftStart || rightStart) {
    if (leftStart && rightStart) return left.localeCompare(right);
    return leftStart ? -1 : 1;
  }
  const leftMission = MISSION_CATEGORY.exec(left);
  const rightMission = MISSION_CATEGORY.exec(right);
  if (leftMission && rightMission) {
    return Number(leftMission[1]) - Number(rightMission[1]) || left.localeCompare(right);
  }
  if (leftMission) return -1;
  if (rightMission) return 1;
  return left.localeCompare(right);
}

function byCategory<T extends ListedChallenge>(sorted: readonly T[]): ChallengeGroup<T>[] {
  const groups = new Map<string, T[]>();
  for (const challenge of sorted) {
    const key = challenge.category || UNCATEGORIZED;
    const bucket = groups.get(key) ?? [];
    bucket.push(challenge);
    groups.set(key, bucket);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => compareCategories(left, right))
    .map(([key, items]) => ({ key, label: key, items }));
}

function byStatus<T extends ListedChallenge>(sorted: readonly T[]): ChallengeGroup<T>[] {
  const groups: ChallengeGroup<T>[] = [
    { key: "not-solved", label: "Not solved", items: sorted.filter((challenge) => !isSolved(challenge)) },
    { key: "solved", label: "Solved", items: sorted.filter(isSolved) },
  ];
  return groups.filter((group) => group.items.length > 0);
}

/** Sort the challenges, then group them for the selected view. Empty groups are omitted. */
export function groupChallenges<T extends ListedChallenge>(
  items: readonly T[],
  view: ChallengeView,
  sort: ChallengeSort,
): ChallengeGroup<T>[] {
  const sorted = sortChallenges(items, sort);
  if (view === "category") return byCategory(sorted);
  if (view === "status") return byStatus(sorted);
  return sorted.length > 0 ? [{ key: "all", label: null, items: sorted }] : [];
}

/** The list state that the URL query parameters select, and the groups it shows. */
export interface ListView<T> {
  view: ChallengeView;
  sort: ChallengeSort;
  layout: ChallengeLayout;
  tagLabels: string[];
  topicLabels: string[];
  activeTag: string | null;
  activeTopic: string | null;
  groups: ChallengeGroup<T>[];
}

/** A label value from the URL applies only when a listed challenge carries it. */
function knownLabel(value: string | null, labels: readonly string[]): string | null {
  return value !== null && labels.includes(value) ? value : null;
}

/**
 * Apply the list query parameters to the rows. The list page and the challenge page
 * both use this function, so the challenge page buttons follow the shown order (#2999).
 */
export function readListView<T extends ListedChallenge & Labeled>(
  items: readonly T[],
  params: URLSearchParams,
): ListView<T> {
  const view = parseView(params.get("view"));
  const sort = parseSort(params.get("sort"));
  const layout = parseLayout(params.get("layout"));
  const tagLabels = distinctLabels(items, "tags");
  const topicLabels = distinctLabels(items, "topics");
  const activeTag = knownLabel(params.get("tag"), tagLabels);
  const activeTopic = knownLabel(params.get("topic"), topicLabels);
  const groups = groupChallenges(filterByLabels(items, activeTag, activeTopic), view, sort);
  return { view, sort, layout, tagLabels, topicLabels, activeTag, activeTopic, groups };
}

/**
 * Return the challenges before and after one challenge in the shown order, across groups.
 * There is no wraparound. A challenge that is not shown has no neighbors, so a caller
 * never falls through to the first row.
 */
export function adjacentChallenges<T extends { id: string }>(
  groups: readonly ChallengeGroup<T>[],
  challengeId: string,
): { previous: T | null; next: T | null } {
  const sequence = groups.flatMap((group) => group.items);
  const index = sequence.findIndex((challenge) => challenge.id === challengeId);
  if (index === -1) return { previous: null, next: null };
  return { previous: sequence[index - 1] ?? null, next: sequence[index + 1] ?? null };
}
