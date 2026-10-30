# KineticLab — Smoke-Test Asset Generation Plan

**Version:** 1.0  
**Status:** Locked input-generation plan for `10.1 Inputs needed`  
**Primary use:** Generate and package first smoke-test video and its validation assets  
**Related plan:** `Docs/KineticLab_Locked_App_Plan.md`

---

## 1. Purpose

This document defines exactly what must exist before the first KineticLab smoke test runs:

- one usable pendulum video,
- one visible metric reference card,
- one independent pendulum-length measurement record,
- media metadata and frame timestamps,
- annotations or synthetic ground truth for inspection,
- reproducible asset provenance,
- and controlled failure variants for parser and ingest tests.

For the first pass, generate one clean clip. Do not generate the full benchmark matrix yet.

## 1.1 Important limitation

An AI-generated video is suitable for:

- media ingest testing,
- frame/timestamp plumbing,
- SAM request/response testing,
- parser testing,
- overlay inspection,
- UI smoke testing,
- and early pipeline wiring.

An AI-generated video is **not automatically valid physical ground truth**. Text-to-video systems can invent motion, change object shape, warp the card, alter the camera, duplicate frames, or violate pendulum dynamics. Do not use an AI-generated clip to claim measurement accuracy or validate `g` until its frame-by-frame geometry has independently been verified.

Preferred hierarchy:

1. **Best:** deterministic Blender or scripted 3D render with known physical parameters.
2. **Acceptable for early smoke test:** AI-generated visual clip plus manual frame annotation and explicit `ground_truth_status: approximate`.
3. **Required for scientific validation:** real camera clip with ruler-measured length and independently recorded setup metadata.

---

## 2. Locked First Asset

Generate one clean, controlled, side-on pendulum clip with these target properties.

| Property | Locked target |
| :-- | :-- |
| Container | MP4 |
| Video codec | H.264/AVC |
| Pixel format | `yuv420p` |
| Resolution | 1280 × 720 or 1920 × 1080 |
| Frame rate | 30 fps constant frame rate for first smoke test |
| Duration | 6 seconds |
| Audio | None required |
| Camera | Fixed, locked tripod view; no pan, tilt, zoom, or focus change |
| View | Side-on, pendulum plane nearly parallel to image plane |
| Pendulum | One bob, one fixed pivot, one visible string |
| Bob | High-contrast matte sphere; no changing texture or shape |
| Card | Generic ISO ID-1 rectangle, visible in same or near plane |
| Background | Plain, low-detail, high contrast with bob and card |
| Motion | At least three visible oscillations if possible |
| Lighting | Stable diffuse lighting; no moving shadows or flicker |
| Text/logos | None; no watermark; no generated labels |
| Camera motion blur | Mild and consistent at most; avoid severe blur in clean clip |
| Occlusion | None in clean clip |

### 2.1 Recommended scene parameters

Use these values for a deterministic render or asset manifest. They are **fixture parameters**, not measured results:

| Parameter | Fixture value |
| :-- | :-- |
| Fixture gravity | `9.81 m/s^2` |
| Pivot-to-bob-center length | `0.65 m` |
| Bob radius | `0.025 m` |
| Initial angle | `18 degrees` |
| Initial angular velocity | `0 rad/s` |
| Damping | `0` for clean ideal clip, or a separately labeled small damping variant |
| Card long side | `0.08560 m` |
| Card short side | `0.05398 m` |
| Card orientation | Slight in-plane rotation, approximately `8 degrees` |
| Camera roll | Approximately `0 degrees` |
| Camera distance | Far enough to keep perspective mild and entire motion visible |
| Object placement | Card and pendulum motion plane as close as physically possible |

Do not place fixture values in a result report as if KineticLab measured them.

---

## 3. Asset Package Layout

Create one self-contained directory per fixture:

```text
assets/
  smoke/
    clean_v1/
      source/
        generated_source.mp4
      media/
        clean_v1.mp4
        clean_v1_frame0.png
        clean_v1_preview.jpg
      metadata/
        manifest.json
        ffprobe_stream.json
        ffprobe_frames.json
        source_notes.md
      truth/
        scene_parameters.json
        bob_centers.csv
        card_corners.csv
        frame_quality.csv
      annotations/
        manual_review.md
        frame_000000.png
        frame_000090.png
        frame_000150.png
      expected/
        smoke_expectations.json
      hashes/
        SHA256SUMS.txt
```

### 3.1 Required files for first smoke test

Only these are mandatory for the first run:

- `media/clean_v1.mp4`
- `media/clean_v1_frame0.png`
- `metadata/manifest.json`
- `metadata/ffprobe_stream.json`
- `metadata/ffprobe_frames.json`
- `metadata/source_notes.md`
- `truth/scene_parameters.json`
- `truth/bob_centers.csv` if known or manually annotated
- `expected/smoke_expectations.json`
- `hashes/SHA256SUMS.txt`

The rest improves inspection but may wait until the first pipeline is working.

### 3.2 Naming rules

- Lowercase names only.
- Use stable fixture IDs such as `clean_v1`, `blur_v1`, `occlusion_v1`.
- Never overwrite an asset after it has been used in a test.
- Create a new version when generation settings change.
- Store source files separately from normalized processing files.

---

## 4. AI Video Generation Strategy

## 4.1 Preferred generation method

Use an image-to-video workflow when possible:

1. Generate or compose one exact reference frame first.
2. Review the frame for card shape, bob, string, pivot, and empty background.
3. Animate that approved frame with locked-camera settings.
4. Reject any clip where the card, bob, pivot, or string changes identity or shape.
5. Normalize the accepted result to H.264 MP4 with FFmpeg.

Image-to-video is preferable because text-to-video often changes geometry across frames.

## 4.2 Recommended generation settings

Use the closest available settings in the chosen generator:

- 6 seconds
- 30 fps output if available
- fixed camera / locked shot
- image-to-video from approved frame
- low-to-moderate motion strength
- no camera movement
- no audio
- no prompt expansion that adds objects
- no automatic cinematic camera movement
- no stylization after the reference frame is approved

The generated source may not actually contain 30 unique, physically correct frames. Record the generator name, model/version, seed, prompt, negative prompt, reference image hash, and export settings in `source_notes.md`.

---

## 5. Master Prompt — Clean Smoke-Test Video

Use this prompt as the starting point. Adapt syntax to the selected generation tool, but preserve scene constraints.

```text
Create a 6-second locked-camera scientific measurement video for a computer-vision smoke test.

Scene: a simple single-plane pendulum experiment filmed from a fixed side-on camera. A small matte red sphere hangs from a thin dark string attached to a clearly visible fixed pivot. The pendulum swings left and right in one vertical plane with smooth continuous motion and approximately three to four complete oscillations during the clip. The pivot stays fixed. The string stays taut and straight. The bob remains the same size, color, texture, and shape in every frame.

Place a generic blank rectangular ISO ID-1 reference card beside the pendulum in the same physical plane as the swing. The card has the proportions of a standard payment card, a plain matte white surface, no logo, no writing, no barcode, no numbers, no recognizable brand, and clearly visible straight edges. The card must remain completely static throughout the video.

Use a plain matte dark-gray background with strong, stable contrast between the red bob, black string, and white reference card. Use soft diffuse lighting with no flicker, no moving shadows, and no reflections. Keep the entire pendulum path, pivot, bob, string, and card inside the frame. Keep the camera optical axis approximately perpendicular to the pendulum plane. Use mild natural motion blur only if it remains consistent and does not deform the bob or card.

The camera is on a rigid tripod. No camera translation, rotation, zoom, focus breathing, rolling camera movement, reframing, or lens change. No cuts. No scene transitions. No additional objects. No people. No hands. No text overlays. No captions. No watermark. No sound.

Visual style: realistic laboratory phone video, neutral color, physically coherent object motion, stable geometry, suitable for frame-by-frame object segmentation and centroid tracking.
```

## 5.1 Negative prompt

```text
camera movement, handheld footage, pan, tilt, zoom, dolly, orbit, reframing, cuts, scene transition, changing focal length, focus breathing, rolling shutter wobble, warped geometry, melting objects, shape changing, object duplication, disappearing bob, disappearing string, broken string, slack string, moving pivot, moving reference card, bending card, curved card, changing card dimensions, card text, logo, barcode, numbers, watermark, subtitles, labels, extra pendulum, extra bob, extra string, extra card, people, hands, fingers, clutter, reflections, glare, flickering light, moving shadows, unstable background, transparent bob, patterned bob, glossy sphere, severe motion blur, heavy depth of field, bokeh, lens flare, particles, smoke, fire, rain, exaggerated cinematic lighting, fast camera shake, impossible motion, teleportation, discontinuous trajectory, frame interpolation artifacts, duplicate frames, compression blocks, low resolution, cropped pivot, cropped bob, cropped card
```

## 5.2 Image-generation prompt for the approved reference frame

Generate this still first if the video tool supports image-to-video:

```text
Scientific pendulum experiment reference frame, fixed side-on laboratory camera, 16:9 composition, plain dark-gray matte background. A small matte red sphere attached to a thin black string hangs from a fixed horizontal pivot near the upper center-left. The sphere is displaced approximately 18 degrees from vertical and fully visible. A blank white ISO ID-1 rectangular reference card is placed beside the pendulum in the same plane, fully visible, with a slight 8-degree in-plane rotation, straight edges, realistic standard payment-card proportions, no logos, no writing, no barcode, no numbers. Stable diffuse light, sharp straight card edges, strong contrast, no people, no hands, no clutter, no watermark, no text, no camera perspective exaggeration. The complete pivot, string, bob path area, and card fit inside the frame. Photorealistic but geometrically stable, suitable as a frame-0 computer-vision calibration fixture.
```

## 5.3 Image-to-video motion prompt

```text
Animate only the red pendulum bob in a smooth, physically coherent left-right swing around the fixed pivot. Keep the camera, background, reference card, pivot, string attachment point, and lighting completely unchanged. Keep the string taut and connected to the same pivot. Keep the bob’s size, color, shape, and texture constant. Preserve the approved frame composition. Produce approximately three to four complete oscillations over 6 seconds. No camera movement, no cuts, no new objects, no text, no watermark, no changes to card geometry.
```

---

## 6. Better Option: Deterministic 3D Fixture Prompt

If an AI coding or 3D-generation tool can create a Blender scene, use this approach instead of text-to-video. It creates known geometry and lets the project export exact frame annotations.

```text
Create a deterministic Blender scene for a computer-vision pendulum smoke test.

Scene requirements:
- Render exactly 180 frames at 30 fps, 1280x720, 6 seconds, H.264-compatible output.
- Use a fixed perspective camera with no animation, no autofocus, no camera shake, and no motion blur for the first clean fixture.
- Create a rigid pendulum: fixed pivot, massless straight string of length 0.65 meters, matte red spherical bob of radius 0.025 meters, initial angular displacement 18 degrees, zero initial angular velocity, and gravity 9.81 meters per second squared.
- Use a deterministic numerical pendulum animation or rigid-body setup with no air drag for the clean fixture.
- Place a blank white rectangular ISO ID-1 card with dimensions 0.08560 by 0.05398 meters in the same plane as the pendulum, fully visible, rotated 8 degrees in-plane, with no text or branding.
- Use a matte dark-gray background and stable diffuse lighting.
- Keep pivot, complete bob path, string, and card in frame at all times.
- Export the bob center coordinates, card corner coordinates, frame index, timestamp, and fixture parameters as machine-readable JSON or CSV alongside the video.
- Render an optional segmentation-color pass with a unique flat color for the bob and another for the card.
- Do not add people, hands, logos, labels, text, sound, extra objects, reflections, or animated lighting.
```

### 6.1 Deterministic render requirements

The render is acceptable as an offline truth fixture only if:

- bob center coordinates are exported from the scene, not estimated from the rendered image;
- card corners are exported from the scene;
- frame count is exactly known;
- timestamps are generated from the declared frame rate;
- the rendered video is visually checked against the exported truth;
- source scene file and generator version are retained.

---

## 7. Truth and Annotation System

## 7.1 Truth status values

Every asset must declare one:

- `exact_render_truth`: generated from deterministic scene geometry;
- `manual_annotation`: positions reviewed frame-by-frame by a person;
- `approximate_ai_visual`: generated by AI but not independently verified;
- `real_capture_reference`: recorded from a physical setup with measurement notes.

The first AI-generated clip should normally be marked `approximate_ai_visual` unless manually annotated.

## 7.2 `scene_parameters.json`

Recommended shape:

```json
{
  "fixture_id": "clean_v1",
  "truth_status": "approximate_ai_visual",
  "source_kind": "image_to_video",
  "duration_seconds": 6.0,
  "frame_rate_nominal": 30.0,
  "expected_frame_count": 180,
  "resolution": [1280, 720],
  "gravity_fixture_m_per_s2": 9.81,
  "pendulum_length_fixture_m": 0.65,
  "bob_radius_fixture_m": 0.025,
  "initial_angle_fixture_deg": 18.0,
  "damping_fixture": 0.0,
  "card_dimensions_m": [0.0856, 0.05398],
  "card_same_plane_assumption": true,
  "notes": "Fixture parameters are generation assumptions, not measured output."
}
```

For an AI-generated clip where values are not guaranteed, set fields to `null` instead of pretending they are exact.

## 7.3 `bob_centers.csv`

For manually annotated or deterministic clips:

```text
frame_index,timestamp_seconds,x_pixels,y_pixels,valid,annotation_method,confidence,notes
0,0.000,812.4,344.1,true,manual,0.95,
1,0.033,809.8,347.0,true,manual,0.95,
```

Rules:

- `frame_index` is zero-based.
- `timestamp_seconds` must come from the frame timestamp manifest.
- `x_pixels` and `y_pixels` use the same image coordinate origin documented by the app.
- Invalid frames remain in the file with `valid=false`; do not delete them.

## 7.4 Annotation method

For a generated clip without exported truth:

1. Extract representative frames.
2. Annotate frame 0, every 5th or 10th frame, and all visibly difficult frames.
3. Review the full trajectory overlay.
4. Record uncertain frames explicitly.
5. Do not label interpolated points as ground truth.
6. Mark the package `manual_annotation` only if the annotated frames were actually reviewed.

The first smoke test does not need perfect annotations for all 180 frames. It does need enough review to detect obvious frame drift, object changes, and card deformation.

---

## 8. Media Normalization

The generated source is not the processing fixture until it passes media checks.

### 8.1 Normalize to H.264 MP4

Use a command equivalent to:

```powershell
ffmpeg -y -i source\generated_source.mp4 -an -c:v libx264 -pix_fmt yuv420p -movflags +faststart -r 30 media\clean_v1.mp4
```

Do not force `-r 30` on a source whose frame timing must be preserved for a VFR test. Use this only for the first clean CFR fixture. Create a separate VFR fixture later.

### 8.2 Extract frame 0

```powershell
ffmpeg -y -i media\clean_v1.mp4 -vf "select=eq(n\,0)" -frames:v 1 media\clean_v1_frame0.png
```

### 8.3 Inspect stream metadata

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,duration -of json media\clean_v1.mp4 > metadata\ffprobe_stream.json
```

### 8.4 Extract per-frame timestamps

```powershell
ffprobe -v error -select_streams v:0 -show_entries frame=best_effort_timestamp_time,pkt_pts_time,pkt_duration_time,width,height -of json media\clean_v1.mp4 > metadata\ffprobe_frames.json
```

If the local FFmpeg build does not expose one of these fields, preserve the fields it does expose and record the limitation in `source_notes.md`. Do not manufacture source PTS and call them hardware timestamps.

### 8.5 Hash assets

```powershell
Get-FileHash media\clean_v1.mp4 -Algorithm SHA256
Get-FileHash media\clean_v1_frame0.png -Algorithm SHA256
```

Write all final hashes to `hashes/SHA256SUMS.txt`.

---

## 9. `manifest.json` Template

```json
{
  "fixture_id": "clean_v1",
  "purpose": "KineticLab smoke test input",
  "status": "candidate",
  "truth_status": "approximate_ai_visual",
  "source": {
    "kind": "image_to_video",
    "provider": null,
    "model": null,
    "model_version": null,
    "seed": null,
    "prompt_file": "source_notes.md",
    "reference_image_sha256": null
  },
  "media": {
    "path": "media/clean_v1.mp4",
    "container": "mp4",
    "codec_expected": "h264",
    "pixel_format_expected": "yuv420p",
    "audio_expected": false,
    "duration_seconds_expected": 6.0,
    "frame_rate_expected": 30.0,
    "frame_count_expected": 180,
    "width_expected": 1280,
    "height_expected": 720
  },
  "experiment": {
    "type": "simple_planar_pendulum",
    "bob_concept": "red sphere",
    "reference_concept": "blank white reference card",
    "card_dimensions_m": [0.0856, 0.05398],
    "independent_length_m": 0.65,
    "independent_length_source": "fixture_parameter_only_not_measurement"
  },
  "expected_smoke_behavior": {
    "bob_visible": true,
    "card_visible": true,
    "camera_fixed": true,
    "track_should_be_continuous": true,
    "expected_failure": null
  },
  "provenance": {
    "created_utc": null,
    "generator_settings_recorded": true,
    "normalization_command_recorded": true,
    "hashes_recorded": true
  }
}
```

Before using the file, replace unknown fields with actual values or `null`. Never leave fictional provider/model values in the manifest.

---

## 10. Expected Smoke-Test Assertions

`expected/smoke_expectations.json` should define expectations without pretending to define scientific accuracy.

```json
{
  "fixture_id": "clean_v1",
  "assertions": [
    "video opens successfully",
    "video has one video stream",
    "video codec is h264 or explicitly documented equivalent",
    "decoded dimensions are nonzero",
    "frame timestamps are monotonic",
    "frame index count is nonzero",
    "frame 0 is extractable",
    "reference card is visible in frame 0",
    "bob is visible in frame 0",
    "normalized observation schema can be populated",
    "missing frames are represented explicitly",
    "no secret appears in logs or manifest"
  ],
  "not_asserted": [
    "gravity accuracy",
    "scientific correctness of AI-generated motion",
    "SAM precision or recall",
    "sub-pixel tracking accuracy",
    "production latency",
    "model-selection correctness"
  ]
}
```

The first smoke test proves that the data path works. It does not prove that KineticLab measures gravity correctly.

---

## 11. Asset Validation Checklist

### 11.1 Visual review

- [ ] Pivot remains fixed.
- [ ] Bob remains one object with stable shape and color.
- [ ] String remains attached and taut.
- [ ] Card remains static and rectangular.
- [ ] Card has no generated text, logo, barcode, or watermark.
- [ ] Card is fully visible.
- [ ] Bob path remains fully visible.
- [ ] No cuts or transitions occur.
- [ ] Lighting does not flicker.
- [ ] Background does not move.
- [ ] No extra objects appear.
- [ ] Frame 0 is useful for calibration inspection.

### 11.2 Media review

- [ ] File opens with FFmpeg.
- [ ] Video stream exists.
- [ ] Codec and pixel format are recorded.
- [ ] Duration is recorded.
- [ ] Frame count is recorded or explained.
- [ ] Frame timestamps are extracted.
- [ ] Timestamps are monotonic.
- [ ] Frame 0 extraction succeeds.
- [ ] File hash is recorded.

### 11.3 Scientific honesty review

- [ ] Fixture status is declared.
- [ ] AI-generated values are not called measurements.
- [ ] Exact truth is claimed only for deterministic render exports.
- [ ] Manual annotations are labeled as manual.
- [ ] Unknown values are `null`, not guessed.
- [ ] No benchmark result is derived from this clip alone.

---

## 12. Failure Variants After Clean Clip

Do not create these before `clean_v1` passes the first smoke test. Then create one variant at a time.

| Fixture | Purpose | Mutation |
| :-- | :-- | :-- |
| `missing_card_v1` | Calibration rejection | Remove or hide card |
| `occlusion_v1` | Missing-frame handling | Hide bob for a short interval |
| `blur_v1` | Motion/segmentation robustness | Add controlled motion blur |
| `tilt_v1` | Geometry warning | Rotate camera or plane modestly |
| `short_clip_v1` | Insufficient-data state | Keep less than three oscillations |
| `id_switch_v1` | Track validation | Add a visually similar distractor |
| `vfr_v1` | Timestamp handling | Create VFR processing fixture without rewriting timestamps silently |
| `malformed_response_fixture` | Parser safety | Hand-edit saved model response, not video |

Every variant must declare its expected failure or warning. Do not use a failure variant as the clean baseline.

---

## 13. Suggested `source_notes.md`

```markdown
# clean_v1 source notes

## Generation

- Source kind: image-to-video / deterministic render / real capture
- Provider:
- Model and version:
- Seed:
- Generation date UTC:
- Reference image hash:
- Prompt file:
- Negative prompt file:
- Generator settings:

## Scene assumptions

- Target duration: 6 seconds
- Target frame rate: 30 fps
- Target resolution: 1280x720
- Bob concept: red sphere
- Card concept: blank white ISO ID-1 card
- Camera: fixed side-on
- Truth status: approximate_ai_visual

## Manual review

- Reviewed by:
- Review date UTC:
- Frames inspected:
- Observed defects:
- Accepted for smoke test: yes/no
- Reason:

## Normalization

- FFmpeg version:
- Normalization command:
- Output hash:
- Notes:
```

---

## 14. First-Day Execution Order

1. Generate one still reference frame.
2. Reject the still if card, pivot, bob, or string is malformed.
3. Animate the approved still with locked-camera settings.
4. Review the entire clip as a frame sequence, not only as a smooth video.
5. Save source media and generation metadata.
6. Normalize to H.264 MP4.
7. Extract stream and frame metadata with FFprobe.
8. Extract frame 0.
9. Create `manifest.json` and `scene_parameters.json`.
10. Manually inspect representative frames.
11. Create `expected/smoke_expectations.json`.
12. Hash final files.
13. Run only the media/parser smoke test first.
14. Run SAM smoke test after local media checks pass.
15. Record all failures; do not silently regenerate until a failure reason is written.

---

## 15. Acceptance Decision

Mark `clean_v1` as `accepted_for_smoke_test` only when:

- the file is valid H.264 MP4 or the deviation is explicitly documented;
- frame 0 contains both required objects;
- the clip has a fixed camera and no scene cuts;
- metadata and timestamps are saved;
- source provenance is recorded;
- truth status is explicit;
- asset hashes are saved;
- and the clip passes visual review.

Mark it `rejected` when any required object changes identity, the card is malformed, the camera moves, the clip contains a cut, timestamps cannot be inspected, or the source provenance is missing.

---

## 16. Final Rule

Use the AI-generated clip to start the smoke-test pipeline, not to prove metrology.

The first proof target is:

```text
media file -> timestamps -> observations -> normalized records -> inspectable output
```

The later proof target is:

```text
real measured experiment -> calibrated observations -> validated fit -> honest uncertainty
```
