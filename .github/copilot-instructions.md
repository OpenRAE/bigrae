---
applyTo: *.*
---

Always review for secure coding best practices in addition to other code review.
Use current secure coding practices and established repository patterns.

Honor the ADR guard in `scripts/adr_guard/adr_guard.py` and the repo-local policy in `AGENTS.md`.
If you change guardrail files or architecture rules, update the ADR docs in `docs/adr/` or `docs/technical/dev/adr-enforcement.md` in the same change.

Private scenario content and executable adapters belong in their owning repositories. Review core changes for scenario-specific branches, scripts, image recipes, and infrastructure. Use synthetic examples in public issues, PRs, review records, and documentation.
Exclude private pack names, repository locations, domains, topology, and answers. Historical disclosure does not authorize repeating private details. Follow the private-scenario boundary in `AGENTS.md`.


For documentation changes, follow the shared skill and explicit-path checks in `CONTRIBUTING.md`. Verify facts against code and preserve technical meaning.
