import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SolvedBadge } from "./SolvedBadge";

// A display name can be 100 characters long. The badge must shrink and
// truncate it rather than overflow the card, and keep the full label reachable.
describe("SolvedBadge", () => {
  it("truncates a long solver name and keeps the full label in the title", () => {
    const name = "N".repeat(100);
    render(<SolvedBadge challenge={{ solved: false, team_solved: true, team_solved_by: name }} />);
    const label = screen.getByText(`Solved by ${name}`);
    expect(label).toHaveClass("truncate");
    const badge = label.closest('[data-slot="badge"]');
    expect(badge).toHaveAttribute("title", `Solved by ${name}`);
    expect(badge).toHaveClass("min-w-0", "max-w-full", "shrink");
  });

  it("renders nothing for an unsolved challenge", () => {
    const { container } = render(<SolvedBadge challenge={{ solved: false, team_solved: false, team_solved_by: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
