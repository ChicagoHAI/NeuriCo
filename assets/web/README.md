# Web UI branding images (fixed, bundled with the app)

These are the product's branding images for the interactive web UI. They ship
**with the code** and are **not** user-configurable — there is no upload feature;
the server only serves these two fixed files read-only.

To set them, place the two files here (developer/build step, done once):

| Filename | Used as |
|---|---|
| `neurico-logo.png` | the NeuriCo logo in the top bar |
| `manager-avatar.png` | the avatar next to "Manager" in the chat |

Notes:
- `.png` preferred; `.svg`, `.jpg`, `.jpeg`, `.webp`, `.gif` also work (same base name).
- A square image looks best for the avatar (shown in a small circle).
- If a file is ever missing, the UI falls back to the default emoji — this is
  just resilience, not a user-facing option.
