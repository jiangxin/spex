<!-- spex:begin:requirement -->
# Requirement

The greeting CLI accepts a name and an optional --upper flag. Add
--separator so users can replace the comma and space after Hello.
The default output remains `Hello, Ada!`. Preserve --upper.

<!-- spex:begin:detailed-design -->
# Design

Use argparse to accept a separator string with a default of comma
followed by space. Apply uppercase after constructing the greeting.

<!-- spex:begin:test-plan -->
# Tests

Verify the default, uppercase, and custom separator outputs.
