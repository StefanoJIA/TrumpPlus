# Remotion Stub

Phase 1.2 does not run Remotion and does not render MP4.

`exports/render_packages/brief_{id}/manifest.json` is designed to be consumed by a future Remotion template. The important fields are:

- `scene_type`: scene category such as `information_card`.
- `duration_seconds`: target duration for the visual scene.
- `image_path`: image asset filename inside the render package directory.
- `subtitle_range`: inclusive subtitle index range to show over the scene.

Future Phase 1.3 work can map `visual_cards` to Remotion compositions, load `subtitles.json`, and render a local MP4 only after human approval. The renderer must preserve the project boundaries: no fake screenshots, no Trump voice impersonation, no lip sync, no unauthorized news images, and no automatic publishing.

