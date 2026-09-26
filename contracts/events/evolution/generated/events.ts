// Generated from contracts/events/evolution/canonical-event-1.1-demo.schema.json. Do not edit.

export interface SourceRef {
  source_id: string;
  source_type: string;
  sequence?: number | null;
}

export interface Duration {
  value: number;
  unit: "ms" | "s" | "min" | "h";
  meaning: string;
}

export interface Defect {
  defect_type: string;
  description?: string | null;
  severity?: string | null;
  component_instance_id?: string | null;
  confidence?: number | null;
}

export interface ItemRegisteredPayload {
  product_definition_id: string;
  revision: string;
  line_id?: string | null;
  route_id?: string | null;
  route_revision?: number | string | null;
}

export interface OperationStartedPayload {
  operation_id: string;
  operator_id: string;
  equipment_id: string;
  station_id: string;
  parameters?: Record<string, unknown> | null;
  previous_operation_run_id?: string | null;
  run_reason?: "production" | "rework";
  rework_for_nonconformance_id?: string | null;
}

export interface OperationFinishedPayload {
  completion_status: "completed" | "failed" | "aborted" | "interrupted";
  duration?: Duration | null;
  stop_reason?: string | null;
  parameters?: Record<string, unknown> | null;
}

export interface InspectionResultPayload {
  inspection_result: "no_defect" | "defect_detected" | "impossible_to_assess";
  observation_quality: "good" | "poor" | "unknown";
  control_point_id: string;
  confidence?: number | null;
  inspection_scope?: Record<string, unknown> | Array<unknown> | null;
  defects?: Array<Defect>;
  evidence_refs?: Array<string>;
  component_instance_id?: string | null;
  control_device_id?: string | null;
  capture_session_id?: string | null;
  analyzer_version?: string | null;
}

export interface MachineStatePayload {
  equipment_id: string;
  state: string;
  code?: string | null;
  parameters?: Record<string, unknown> | null;
}

export interface OperatorActionPayload {
  operator_id: string;
  action_type: string;
  parameters?: Record<string, unknown> | null;
}

export interface ControlDeviceInvalidatedPayload {
  device_id: string;
  affected_from: string;
  affected_to: string;
  reason: string;
  invalidation_type?: string | null;
  supporting_evidence_refs?: Array<string>;
}

export const EVENT_TYPES = ["control_device.invalidated", "inspection.result", "item.registered", "machine.state", "operation.finished", "operation.started", "operator.action"] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export const SCHEMA_REGISTRY = [
  { event_type: "control_device.invalidated", schema_version: "1.1" },
  { event_type: "inspection.result", schema_version: "1.1" },
  { event_type: "item.registered", schema_version: "1.1" },
  { event_type: "machine.state", schema_version: "1.1" },
  { event_type: "operation.finished", schema_version: "1.1" },
  { event_type: "operation.started", schema_version: "1.1" },
  { event_type: "operator.action", schema_version: "1.1" },
] as const;

export interface PayloadModels {
  "item.registered": ItemRegisteredPayload;
  "operation.started": OperationStartedPayload;
  "operation.finished": OperationFinishedPayload;
  "inspection.result": InspectionResultPayload;
  "machine.state": MachineStatePayload;
  "operator.action": OperatorActionPayload;
  "control_device.invalidated": ControlDeviceInvalidatedPayload;
}
