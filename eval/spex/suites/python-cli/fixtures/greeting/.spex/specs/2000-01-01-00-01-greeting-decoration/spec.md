<!-- spex:begin:requirement -->
# Requirement

Allow users to decorate a greeting with independent `--prefix TEXT`
and `--suffix TEXT` options. Default both to the empty string.
Apply --upper to the greeting before decorating it. The prefix and
suffix are added verbatim.

<!-- spex:begin:detailed-design -->
# Design

Add the prefix first as a separate working increment. Add the suffix
in the second increment. Keep the greeting and the existing CLI
behavior compatible in both increments.

<!-- spex:begin:test-plan -->
# Tests

Run the existing CLI tests. Cover prefix only, suffix only and both
options with --upper, including verbatim handling of decoration text.
