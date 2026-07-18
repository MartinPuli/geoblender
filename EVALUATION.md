# Evaluation: measuring whether a render passes as real

The differentiator is not merely OSM to Blender; it is the loop:

`place -> scene -> render -> compare with reality -> correct -> repeat`

This document defines the perceptual evaluation protocol for that loop.

## Principles

1. **Prefer forced choice over an isolated 0–100 score.** Present a render and a
   pose-matched real crop as a 2AFC task: “Which image is real?” The primary
   metric is discriminator accuracy. About 50% means indistinguishable in that
   test; above 75% means the CG image is usually obvious. Keep 0–100 scores only
   as secondary diagnostics.
2. **Control confounds before comparing.** Match FOV, heading, pitch, crop, and
   capture time where possible so the judge does not punish pose or lighting
   differences as realism defects.
3. **Freeze references and keep a held-out set.** Split real views into a tuning
   set for selecting fixes and an evaluation set that is never optimized against.
4. **Use a diverse, anchored panel.** Evaluate materials, geometry,
   lighting/atmosphere, and gestalt with at least two distinct model families.
   The model that proposed a fix must not be its only evaluator.
5. **Constrain judge output.** Require structured fields such as evidence,
   defect, severity, proposed fix, confidence, and verdict. Evidence must precede
   the verdict.
6. **Debias pairwise comparisons.** Randomize image order, run both A/B orders,
   and average. Treat an order-dependent flip as a tie or discard it.
7. **Anchor with independent metrics.** On pose-matched data, track CMMD/CLIP-MMD,
   CLIP-IQA, and optionally a real-vs-synthetic detector. Automated metrics do
   not replace the panel.
8. **Aggregate by severity and cross-family consensus.** Deduplicate defects by
   root cause. A single mention is not enough to promote a global fix. Correct
   the highest-impact consensus defect, then remeasure.
9. **Freeze and calibrate the judge contract.** Persist model/version, prompt
   hash, decoding parameters, order randomization, and a small known-real control
   set in `report.json`.
10. **Use periodic human checks.** Run occasional human 2AFC evaluations on the
    held-out set under controlled viewing conditions to recalibrate automation.
11. **Compare candidate fixes directly.** When choosing between two variants,
    compare both against the same real reference and ask which is closer, with
    swapped order.
12. **Pre-register the stopping rule.** Track held-out discriminator accuracy
    with confidence intervals, CMMD, synthetic probability, CLIP-IQA, and the
    deduplicated defect list. Stop only when the registered multi-metric gates
    pass or progress stalls.

## Current implementation

- Implemented: eight-dimension scoring, prioritized defects, source-aware color,
  a frozen different-azimuth holdout camera, tuning/validation score separation,
  an eight-point generalization-gap gate, camera-signature freezing, per-iteration
  deltas/checkpoints, and holdout-ranked best-result restoration.
- Planned: stronger automatic pose matching, building-mask extraction,
  multi-family automated panel execution, swap-averaged 2AFC,
  CIEDE2000/SSIM/LPIPS diagnostics, calibration, and a stopping dashboard.

## Building-detail protocol

Evaluate building identity from coarse to fine. Do not tune windows while the
mass is wrong.

1. **Footprint and mass:** coverage, centroid, orientation, height, and volume.
2. **Silhouette:** roofline, setbacks, towers, voids, and dominant proportions.
3. **Facade grammar:** floor count/rhythm, bay count/rhythm, opening ratio, and
   ground-floor distinction.
4. **Surface class:** masonry, concrete, glass, metal, wood, or unknown.
5. **Microdetail:** frames, mullions, parapets, and texture variation only after
   the higher levels pass.

Use OSM `height`, `building:levels`, `building:part`, `building:material`,
`building:colour`, and roof tags when present. Keep procedural openings labeled
as inferred. Never add a core rule based on a building or city name.

## Color protocol

Keep facade and roof channels separate. Aerial imagery usually observes the
roof; street-level imagery observes facades under lighting and camera response.

1. Lock pose, exposure, view transform, and light before comparing color.
2. Compare only matched building masks; exclude sky, vegetation, cast shadows,
   deep occlusion, and specular highlights.
3. Convert sRGB inputs to scene-linear values for Blender shading.
4. Use median/trimmed Lab color and CIEDE2000 as diagnostics, not a raw-pixel
   target or a standalone acceptance gate.
5. Check a different time/view holdout before accepting a palette correction.
6. Preserve source priority: explicit OSM > verified run measurement > material
   prior > semantic prior > deterministic neutral fallback.

## Technical references

- [Blender color management](https://docs.blender.org/manual/en/latest/render/color_management.html)
  documents scene-linear rendering, AgX, and neutral display transforms.
- [Blender Principled BSDF](https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/principled.html)
  defines base color, roughness, metallic, IOR, and normal behavior.
- [OSM Simple 3D Buildings](https://wiki.openstreetmap.org/wiki/Simple_3D_buildings)
  defines interoperable height, level, material, color, and roof semantics.
- [Sharma et al., CIEDE2000 implementation notes](https://doi.org/10.1002/col.20070)
  provide the perceptual color-difference formula and validation data.
- [Wang et al., SSIM](https://ieeexplore.ieee.org/document/1284395) and
  [Zhang et al., LPIPS](https://github.com/richzhang/PerceptualSimilarity)
  provide complementary structural and learned perceptual diagnostics; neither
  replaces held-out evaluation.

## Honest target

“Indistinguishable” is asymptotic. An adversarial panel will still find
photogrammetry artifacts in 3D Tiles or inferred materials in the OSM pipeline.
The operational goal is held-out discriminator accuracy near 50%, not a literal
100 from a strict subjective judge.
