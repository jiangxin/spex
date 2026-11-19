# Spec Assets (Images)

Shared image handling for `/spex create` and `/spex modify`.

## Discovery

Find pasted images in conversation markers such as
`[Image: source: <path>]` or inline content and resolve their local
paths. Also check explicitly named local images in the requirement or request.
Supported extensions are `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`,
`.webp`, and `.bmp`. Skip asset work when there are no images.

## Copy + Register

- Create `$spec_path/assets/` and copy images there with their original
  filenames.
- Link images in `spec.md` as `![description](assets/filename.png)`.
- Register paths relative to `$spec_path` at the time specified below:

   ```bash
   $spex_skill_dir/scripts/spex meta-helper "$spec_name" prompts \
     --add-images assets/file1.png assets/file2.png
   ```

## Timing Notes

- **create**: copy before or while writing `spec.md` with the links,
  then register after saving the spec.
- **modify**: copy and register when saving the request. Add the links
  when updating `spec.md`.
