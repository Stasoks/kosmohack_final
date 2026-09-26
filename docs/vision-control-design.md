# VisionQC and OperatorVision design assumptions

TRACE-Q consumes already structured observations; this document describes the external visual-control concept requested by the case, not an industrially validated camera specification.

## PROJECT ASSUMPTION — candidate capture cell

The demo design assumes 3–4 fixed industrial cameras per control point, area-scan sensors with global shutter, approximately 12 MP resolution, hardware-triggered acquisition, about four views per item, and 1–2 frames per view. The target processing latency is P95 ≤ 2 seconds, with an operational timeout around 5 seconds. These are project assumptions and require validation on representative parts, finishes, cycle times, optics, lighting, and compute.

**PROJECT ASSUMPTION — requires validation on real optics/material/lighting/defect.**

A first-order sampling estimate for a 200 mm field of view across 4096 pixels is `200 / 4096 ≈ 0.049 mm/px`. A feature spanning 4–6 pixels is therefore roughly 0.2–0.3 mm. This is not a guaranteed minimum detectable defect: optics, focus, contrast, surface finish, blur, lighting, labeling quality, and the required false-negative rate must be measured.

Proposed control points are incoming inspection, post-machining, and final assembly. Each uses fixed cameras with diffuse, repeatable illumination and a calibrated fixture. Incoming/post-operation pairs should use the same pose and optical setup so change detection is meaningful. Reflective surfaces may require cross-polarized lighting or structured illumination. Occlusion, oil, chips, glare, vibration, focus drift, and part-placement variation can make visual assessment impossible.

External VisionQC should report defect class, component/area, confidence when available, observation quality, device ID, capture session, and optional media references. `analyzer_version` is potential future evolution metadata and is not a current P0 contract field. Candidate classes in the synthetic demo are surface cracks, scratches/gouges, dents/deformation, contamination, and selected assembly-presence checks.

Calibration must cover camera intrinsics, lens distortion, pose/fixture repeatability, illumination stability, scale, trigger timing, and device-validity intervals. A visual station can be strong, partial, or incapable for each defect/component key; the route capability matrix records that limit. Dimensional tolerances need calibrated metrology, while subsurface defects and many weld-integrity claims may require NDT rather than ordinary area-scan imaging.

Product identity should come from a fixture/reader or MES operation context and be cross-checked, not inferred silently. OperatorVision emits structured actions, while machine logs remain a separate source; temporal correlation is context, not automatic fault attribution.

Local edge processing limits raw-media movement in a closed production network. The central TRACE-Q node receives signed/authenticated structured outcomes; media stays in the industrial evidence store and is referenced. During connection loss, the edge agent uses store-and-forward with stable event IDs and source sequences; timeout is not converted into GOOD. Poor image produces poor/unknown quality, low confidence remains explicit data for policy evaluation, and an impossible view or unavailable/expired device yields `impossible_to_assess` or invalidated evidence.

The output boundary is a structured observation plus evidence references. VisionQC does not issue the final NCR disposition, establish root cause, or apply containment; those remain TRACE-Q policy and authorized human decisions.

Resolution, frame rate, latency, storage load, and minimum detectable defect are project assumptions until measured on representative parts, finishes, lighting, motion, and accepted false-positive/false-negative targets. Model onboarding requires controlled data collection, expert confirmation, versioned training/configuration, validation by defect class and operating condition, release approval, monitoring, and rollback. Final NCR disposition remains human-controlled.
