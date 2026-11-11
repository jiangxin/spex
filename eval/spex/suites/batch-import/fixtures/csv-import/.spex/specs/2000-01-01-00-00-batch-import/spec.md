# Resumable CSV import

Keep the existing `python3 import_csv.py INPUT DATABASE` command and its
single transaction, output, and first-write-wins duplicate handling.
Add opt-in batching with `--batch-size N` and resume with `--resume`
and an optional `--batch-size N` (default 2 when resuming). N must be
a positive integer. Use only the Python standard library.

## Checkpoint

One checkpoint per database lives in the existing
`import_checkpoint(id, data)` table at id 1. Legacy JSON contains
`committed_rows` and `sha256`. Treat it as version 1 and incomplete.
Write version 2 JSON with `version: 2`, `committed_rows`, `sha256`,
and boolean `complete`. Reject an unknown version. Reading must not
create or modify a table or checkpoint. Expose
`checkpoint.read_checkpoint(connection)` returning the normalized
dictionary or None, and
`checkpoint.write_checkpoint(connection, *, committed_rows, sha256, complete)`
without committing or rolling back the caller's transaction.

## Batch and resume

Expose `importer.import_batch(connection, batch, *, committed_rows, sha256, complete)`
where batch is an iterable of CSV data rows, and committed_rows is the
count before this batch. The helper owns the batch transaction. It
validates each row, inserts new records, and writes the resulting
checkpoint in the same transaction. Progress includes duplicate rows
and excludes the CSV header. A failed batch leaves previous batches
committed and changes neither its own records nor their checkpoint.
An empty final batch can mark a header-only input complete.

Read the input bytes once per command, hash those bytes with SHA-256,
and parse those same bytes. Keep `import_csv.main(argv=None)` and
`import_csv.open_database(path)` callable for tests. Resume skips exactly
committed_rows data rows. A final short batch completes the import.
An identical completed resume is a successful no-op. Missing checkpoint,
invalid batch size, and starting a new batch import over an incomplete
checkpoint produce a nonzero exit and a diagnostic on stderr. A
completed checkpoint may be replaced by an explicit new batch import.

Before resume writes or upgrades anything, compare the current input
fingerprint with the stored fingerprint, including for a completed
checkpoint. Different bytes must fail with a clear stderr diagnostic
and leave records and checkpoint untouched. The same bytes at a
different path are valid. Legacy whole-file mode does not use checkpoints.

## Delivery

Complete the four todo entries in order, with one Git commit per step.
Include a regression test for each step. Run the existing legacy tests
and keep the working tree clean.
