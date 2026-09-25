# VisionQC and OperatorVision design assumptions

TRACE-Q consumes already structured observations; this document describes the external visual-control concept requested by the case, not an industrially validated camera specification.

Proposed control points are incoming inspection, post-machining, and final assembly. Each uses fixed cameras with diffuse, repeatable illumination and a calibrated fixture. Incoming/post-operation pairs should use the same pose and optical setup so change detection is meaningful. Reflective surfaces may require cross-polarized lighting or structured illumination. Occlusion, oil, chips, glare, vibration, focus drift, and part-placement variation can make visual assessment impossible.

External VisionQC should report defect class, component/area, confidence when available, observation quality, device ID, capture session, analyzer version, and optional media references. Candidate classes in the synthetic demo are scratches and burrs. Dimensional tolerance, weld integrity, and minimum defect size require metrology-grade calibration, resolution studies, and possibly non-visual sensors; ordinary video must not be presented as proof of compliance.

Product identity should come from a fixture/reader or MES operation context and be cross-checked, not inferred silently. OperatorVision emits structured actions, while machine logs remain a separate source; temporal correlation is context, not automatic fault attribution.

Local edge processing limits raw-media movement in a closed production network. The central TRACE-Q node receives signed/authenticated structured outcomes; media stays in the industrial evidence store and is referenced. During loss of connection, the edge agent queues events with stable IDs/source sequences. Poor image, low confidence, calibration expiry, or unavailable device yields poor/unknown quality or `impossible_to_assess`, never an invented GOOD.

Resolution, frame rate, latency, storage load, and minimum detectable defect are project assumptions until measured on representative parts, finishes, lighting, motion, and accepted false-positive/false-negative targets. Model onboarding requires controlled data collection, expert confirmation, versioned training/configuration, validation by defect class and operating condition, release approval, monitoring, and rollback. Final NCR disposition remains human-controlled.
