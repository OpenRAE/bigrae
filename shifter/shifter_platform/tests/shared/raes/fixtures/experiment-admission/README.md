# Synthetic experiment inputs

These synthetic inputs come from the MIT-licensed raes-env-packs 7.2.2 source distribution,
`tests/fixtures/experiment-artifact-set`. The adjacent LICENSE preserves the upstream notice.
Tests assemble pack metadata through the existing `make_pack` fixture.
The inputs exercise model and prompt alternatives with repeated trials; no model is called.
The local derivative uses two repetitions and a public seed for randomized allocation.
It adds actual synthetic prompt files and regenerates their descriptor pins through RAES.
