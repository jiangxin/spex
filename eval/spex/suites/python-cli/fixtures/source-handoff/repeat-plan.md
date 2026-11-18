# Greeting repetition rollout

The CLI currently emits one greeting per invocation. Callers buffer the
result in memory, so bound the new option to integers from 1 through 5.

1. Add a reusable count validator and its tests. This increment leaves
   the CLI behavior unchanged.
2. Wire the validator into argparse as `--repeat COUNT`. Default to 1
   and print exactly COUNT copies of the formatted greeting, one per
   line. Preserve the existing name argument and `--upper` behavior.
   For invalid counts, exit 2 with an error on stderr and leave stdout
   empty. The diagnostic must identify `--repeat` and the allowed range.
   For example, `python3 greet.py Ada --repeat 6` must produce no greeting.
   Retrying with `--repeat 2` must print two greetings.

Pair each increment with tests. Cover the default output, both inclusive
bounds, repeated uppercase output, non-integers, and out-of-range counts.
Run `python3 -m unittest -v`.

Consider a `GREET_REPEAT` environment default for a later rollout. It
would change invocations that omit the flag, so confirm its scope first.
