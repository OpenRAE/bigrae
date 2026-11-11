<!-- GEN-2003 requires the imported contribution template to remain verbatim.
Source: https://github.com/PaloAltoNetworks/.github/blob/master/CONTRIBUTING.md
Source blob: 8171634e9574577d0d0222023d582f98044ccd47
Only this preserved policy block is excluded; project addenda below are checked. -->
<!-- vale off -->
<!-- ste-disable -->
# How to contribute

:+1::tada: First off, thanks for taking the time to contribute! :tada::+1:

It's people like you that make security open source such a force in preventing
successful cyber-attacks. Following these guidelines helps keep the project
maintainable, easy to contribute to, and more secure. Thank you for taking the
time to follow this guide.

## Where to start

There are many ways to contribute. You can fix a bug, improve the documentation,
submit bug reports and feature requests, or take a first shot at a feature you
need for yourself.

Pull requests are necessary for all contributions of code or documentation.

## New to open source?

If you're **new to open source** and not sure what a pull request is, welcome!!
We're glad to have you! All of us once had a contribution to make and didn't
know where to start.

Even if you don't write code for your job, don't worry, the skills you learn
during your first contribution to open source can be applied in so many ways,
you'll wonder what you ever did before you had this knowledge. It's worth
learning.

[Learn how to make a pull request](https://github.com/PaloAltoNetworks/.github/blob/master/Learn-GitHub.md#learn-how-to-make-a-pull-request)

## Fixing a typo, or a one or two line fix

Many fixes require little effort or review, such as:

> - Spelling / grammar, typos, white space and formatting changes
> - Comment clean up
> - Change logging messages or debugging output

These small changes can be made directly in GitHub if you like.

Click the pencil icon in GitHub above the file to edit the file directly in
GitHub. This will automatically create a fork and pull request with the change.
See:
[Make a small change with a Pull Request](https://www.freecodecamp.org/news/how-to-make-your-first-pull-request-on-github/)

## Bug fixes and features

For something that is bigger than a one or two line fix, go through the process
of making a fork and pull request yourself:

> 1. Create your own fork of the code
> 2. Clone the fork locally
> 3. Make the changes in your local clone
> 4. Push the changes from local to your fork
> 5. Create a pull request to pull the changes from your fork back into the
>    upstream repository

Please use clear commit messages so we can understand what each commit does.
We'll review every PR and might offer feedback or request changes before
merging.

<!-- ste-enable -->
<!-- vale on -->

## BigRAE project specifics

Use this how-to guide to prepare a contribution.
The imported policy above remains verbatim under GEN-2003.
The steps below apply to this repository.

1. Start a feature branch from `dev`.
2. Follow [local development setup](docs/technical/dev/local-setup.md).
3. Install both commit-hook types:

   ```bash
   pre-commit install --hook-type pre-commit --hook-type commit-msg
   ```
4. Make the change and update its documentation.
5. Select targeted tests from the [testing reference](docs/dev/testing.md).
6. Run the checks for the changed files. Keep full suites in CI.
7. Open the PR against `dev` with source and verification evidence.
8. Fix failed checks and review findings before the maintainer reviews the merge.

Use a Conventional Commit title: `<type>(<optional-scope>): <subject>`.
Use a lowercase subject. The `pr-title-lint` workflow checks the title.
Use `feat`, `fix`, or `perf` when the change should produce a release.
Use a `!` marker for a breaking change.

Feature PRs merge into `dev` through the merge queue, which squash-merges them.
Release promotion preserves those subjects on `main`.
Follow the [development and release workflow](docs/DEVELOPMENT_WORKFLOW.md) for approval and merge methods.

`main` is the stable release line. Feature PRs target `dev`.
CI runs full suites and coverage gates according to the existing quality ownership contract.
The [command matrix](docs/dev/testing.md#command-matrix) lists commands and their CI owners.
`make policy` runs the repository policy checks; it is not a full test suite.

ADR enforcement, exceptions, and the registry live under [`docs/adr/`](docs/adr/);
guardrail file changes (workflows, pre-commit config, `.gitleaks.toml`, etc.)
must keep the ADR registry or `docs/adr/exceptions.yaml` honest.

`CHANGELOG.md` and the product version are owned by
[release-please](https://github.com/googleapis/release-please), which derives
both mechanically from the Conventional Commit history on `main`; do not
hand-edit `CHANGELOG.md` or add changelog fragments. See
[`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md) for the release
model.

Deployment-specific configuration (domain names, alarm emails, GCP project IDs,
SSH keys, etc.) is supplied via gitignored `local.auto.tfvars` files or GitHub
secrets/repository variables, never hardcoded in the committed tree. The full
inventory is in [`docs/dev/deploy-secrets.md`](docs/dev/deploy-secrets.md).

Review the [current-state handbook](docs/technical/architecture.md) when an architecture interface changes.
The documentation coverage manifest maps affected source paths to their technical pages.

For account or installation help, follow [SUPPORT.md](SUPPORT.md).
Report suspected vulnerabilities through [SECURITY.md](SECURITY.md).


## Documentation

Choose a Diataxis purpose: tutorial, how-to guide, reference, or explanation.
Landing pages can route readers to those forms.
Verify current claims against code. Verify historical claims against their source revision.
Preserve technical meaning, quantities, conditions, obligations, commands, identifiers, and useful links.
Record source paths, revision, checks, results, and corrected differences in the PR.

Use the [shared documentation skill](https://github.com/OpenRAE/doc-tools/tree/v0.1.0/skills/documentation).
Its guidance covers Diataxis and ASD-STE100 writing without a second local style guide.
Install its pinned version through your agent's supported mechanism.

For Claude Code:

```text
/plugin marketplace add OpenRAE/doc-tools#v0.1.0
/plugin install doc-tools@openrae-doc-tools
```

For Codex, use the preinstalled skill installer:

```shell
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo OpenRAE/doc-tools --path skills/documentation --ref v0.1.0
```

An existing personal skill with the same name can conflict.
Follow the package's [installation and upgrade guide](https://github.com/OpenRAE/doc-tools/blob/v0.1.0/docs/how-to-install.md).
Skill installation is separate from tool setup.

From the repository root on Linux x64, install the checksum-verified tools:

```shell
make docs-tools
```

Automatic Vale setup currently supports Linux x64.
The shared package documents its additional STE platforms.
Check explicit changed paths, including staged, unstaged, or new files:

```shell
.tools/vale/current/vale CONTRIBUTING.md path/to/page.md
bash .tools/doc-tools/0.1.0/tools/ste-lint.sh CONTRIBUTING.md path/to/page.md
```

Use actual file paths in place of the example path.
Quote filenames that contain spaces.
These commands do not change the files.
The STE wrapper refuses an invocation without paths.

CI reports legacy finding counts and checks rewritten pages listed in `.ste-required.txt`.
Add a page to that list after its full rewrite passes both tools.
Keep preserved records out through narrow, documented exclusions.
Edit generated prose at its maintained source.

The selected STE checks cover contractions, sentence length, and paragraph length.
They run locally with the dictionary and remote analyzer disabled.
Passing them does not prove full STE conformance, factual accuracy, or a clear Diataxis purpose.
Review those properties separately against the [official STE source](https://www.asd-ste100.org/).

Check rendered headings, descriptive links, and diagram alternatives.
Check keyboard access when navigation changes.
Do not use color alone to convey meaning.

For an upgrade or rollback, review the release notes and restore or update the recorded version and checksums.
Keep the installer, Makefile, Vale configuration, and skill references aligned.
Run the targeted checks before changing the pin in a PR.
The existing [ADR enforcement reference](docs/technical/dev/adr-enforcement.md#docs-prose-vale) describes the migration gates and exclusions.
