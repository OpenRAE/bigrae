# Development and release workflow

Use this how-to guide to submit a change or promote a release.
The reference sections describe branch roles and release effects.
The root Makefile and release workflows implement the commands.

## Branch model

| Branch | Role |
| --- | --- |
| `dev` | Integration branch for feature and fix PRs |
| `main` | Stable release line; accepts promotion, release-please, and their approved release changes |

Feature PRs and automated dependency bumps target `dev`.
A push to either branch runs validation; it does not authorize a tenant deployment.
See [CI/CD](technical/dev/ci-cd.md#trigger-rules) for deployment triggers.

## Pull-request flow

1. Start a feature branch from `dev`.
2. Follow the [contribution guide](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md).
3. Run targeted checks for the changed behavior.
4. Open the PR against `dev`.
5. Use a Conventional Commit title: `<type>(<optional-scope>): <subject>`.
6. Use a lowercase subject.
7. Fix failed CI checks and review findings.
8. Leave the feature-PR merge decision to the user or authorized maintainer.

The `pr-title-lint` workflow validates titles on PRs to `dev` and `main`.
Feature PRs merge into `dev` through the merge queue, which squash-merges them.
The validated title becomes the commit subject that release-please reads after promotion to `main`.

The `dev` merge queue runs the required checks again on each merge group.
A PR that fails a check on its merge group leaves the queue and does not merge.
See [CI/CD](technical/dev/ci-cd.md#merge-queue) for the queue configuration.

Do not hand-edit `CHANGELOG.md` or add changelog fragments.
Release-please owns the changelog and product version.

## Promoting dev to main

This procedure requires authority to create the promotion PR.
Merging into `main` requires the user's synchronous approval.
Agents must not infer release authority from an implementation request.
When the user invokes the release skill, use its release script for the three checked release merges.
Do not perform those merges by another route.

1. Confirm the clone's default repository with `gh repo set-default --view`.
2. Compare it with `github_repo` in `.ground-control.yaml`.
3. If no default exists, set it with `gh repo set-default <owner>/<repo>`.
4. Open the promotion PR:

   ```bash
   make devmain
   ```

5. Review the PR destination, source revisions, and check results.
6. Obtain the required approval before merging into `main`.
7. Merge the promotion PR with a merge commit. Never squash it.

`make devmain` opens one PR with head `dev`, base `main`, and title `chore(main): promote dev`.
It supplies the clone's default repository explicitly.
`DEVMAIN_REPO=<owner>/<repo>` overrides that default for an authorized repository.
The target stops when neither source supplies a repository.
It does not merge the PR.

An unqualified `gh pr create` can select a fork's parent repository.
The explicit repository prevents that destination error.
A promotion squash would collapse the feature commit subjects and lose their separate release signals.
The maintainer must select the merge method; no check enforces it.

The promotion title satisfies the required `Lint PR title` context on `main`.
The promotion preserves feature subjects, so its own title is not the release signal.

## Release model

This section explains the release mechanism.
[Release-please](https://github.com/googleapis/release-please) runs on `main` under ADR-042.
`release-please-config.json` and `.release-please-manifest.json` configure it.

BigRAE has one root package with `release-type: simple`, one `vX.Y.Z` tag, and one root `CHANGELOG.md`.
`version.txt` mirrors the product version as repository metadata.
It is not an application runtime setting.
Component `pyproject.toml`, `package.json`, and `Chart.yaml` versions retain their independent meanings.

After pushes to `main`, release-please maintains a PR named `chore(main): release X.Y.Z`.
That PR updates `version.txt` and prepends changelog entries from commits since the last release.
Merging it creates the tag and GitHub Release.
The `sync-dev` job opens a `main` to `dev` back-merge PR for the version and changelog.
A maintainer merges that PR. Automation never force-updates `main` or `dev`.

### What bumps the version

This table is reference for commit subjects on `main`.

| Commit subject | Effect |
| --- | --- |
| `feat:` | Minor bump |
| `fix:` or `perf:` | Patch bump |
| `feat!:`, `fix!:`, or a `BREAKING CHANGE:` footer | Major bump |
| `docs`, `chore`, `refactor`, `test`, `ci`, `build`, `revert` | No bump |
| Retained types: `security`, `added`, `changed`, `deprecated`, `removed`, `fixed` | No bump |

The retained types remain valid PR titles for continuity.
Use `feat`, `fix`, `perf`, or a breaking marker when a change should produce a release.

### What a release is, and is not

A release identifies a source revision through a `vX.Y.Z` tag and GitHub Release bound to one `main` commit.
It does not identify a deployment, package publication, or container image.
Deployment uses the exact source revision and verified OCI image digest under ADR-037.
A SemVer tag is never a deployment trigger or image selector.

The workflow's ephemeral `GITHUB_TOKEN` creates the release PR, tag, and GitHub Release.
Required checks do not automatically run on a release PR opened with that token.
An authorized maintainer handles its protected-branch merge.

## Towncrier to release-please transition (#1776)

This section is historical explanation. Do not repeat its activation procedure for routine releases.
The cutover collected pending towncrier fragments into `## [3.103.0]` without changing their content.
It removed `towncrier.toml`, the consumed fragment directory and template, and the `CHANGELOG.md merge=union` attribute.
Retained fragments elsewhere in Git history or the checkout are historical records, not a current authoring route.

### One-time activation runbook (maintainer, on `main`)

The historical activation required two protected-branch actions after the dev-side cutover:

1. Promote `dev` to `main` with a merge commit that preserves feature subjects.
2. Create baseline tag `v3.103.0` and its matching GitHub Release at the promotion commit.

The manifest recorded `3.103.0` as the baseline.
Subsequent pushes let release-please prepare `3.104.0` and later releases from newer commits.
Routine releases require no repeated baseline tag.
