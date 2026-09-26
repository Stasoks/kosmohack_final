// Generated from contracts/events/evolution/canonical-event-1.1-demo.schema.json. Do not edit.

export interface SourceRef {
  source_id: string;
  source_type: string;
  sequence?: number | null;
}

export interface Defect {
  defect_type: string;
  component_instance_id?: string | null;
}

export interface InspectionResultPayload {
  inspection_result: "no_defect" | "defect_detected" | "impossible_to_assess";
  observation_quality: "good" | "poor" | "unknown";
  control_point_id: string;
  confidence?: number | null;
  inspection_scope?: Record<string, unknown> | Array<unknown> | null;
  defects?: Array<Defect>;
  evidence_refs?: Array<string>;
  analyzer_version?: string | null;
}

export const EVENT_TYPES = ["inspection.result"] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export const SCHEMA_REGISTRY = [
  { event_type: "inspection.result", schema_version: "1.1" },
] as const;

export interface PayloadModels {
  "inspection.result": InspectionResultPayload;
}
