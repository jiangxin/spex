# Spec Assets (Images)

Shared image handling for `/spex create` and `/spex modify`.
Load and follow this document when a command says to process
spec images / assets.

## Discovery

CHECK images from either source (ext: `.png`, `.jpg`, `.jpeg`,
`.gif`, `.svg`, `.webp`, `.bmp`):

- Pasted images (primary): scan conversation for markers
  (e.g. `[Image: source: <path>]`) or inline image content;
  extract absolute paths (agent-cached local dirs)
- Explicit file paths (secondary): local image paths in the
  requirement / request text with a supported extension

IF none found -> skip this reference (no assets work).

## Copy + Register

IF images found:

1. `mkdir -p $spec_path/assets/`
2. Copy each image into `$spec_path/assets/`, keep original
   filename
3. Register in `meta.json` (example):

   ```bash
   $spex_skill_dir/scripts/spex meta-helper $spec_name prompts \
     --add-images assets/file1.png assets/file2.png
   ```

4. In `spec.md`, reference via Markdown image links:

   `![description](assets/filename.png)`

## Timing Notes

- **create**: discover + copy before / while writing `spec.md`;
  register with `meta-helper --add-images` after `spec.md` is
  written; embed `![...](assets/...)` links in the new spec
- **modify**: discover + copy + register when saving the request;
  embed `![...](assets/...)` links when updating `spec.md` later

Paths passed to `--add-images` are relative to `$spec_path`
(e.g. `assets/file1.png`), not absolute host paths.
