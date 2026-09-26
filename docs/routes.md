# Configurable routes

Routes are stored as `RouteDefinition → RouteRevision → RouteStep[]`; no route is hardcoded into replay. A step may carry a `ControlPointPolicy` reference through:

```text
control_point_id, operation_id, required, inspection_scope, trust_policy_id
```

The technologist can create/import a route, clone its ordered step array into a new draft revision, edit JSON, activate it, and export the resulting structure. The UI intentionally uses ordered JSON rather than drag-and-drop.

Activation makes the revision immutable and supersedes the former active revision. Registration resolves the active revision once and stores it on the item. Later route changes do not alter an already started item.

If a following route operation starts without the required preceding inspection, replay adds `MISSING_CHECK` as analysis limitation. It never fabricates an inspection event.

## Inspection capability

`inspection_scope` can use the legacy component/defect allow-list or a per-key capability matrix:

```json
{
  "coverage": {
    "COMP-HOUSING-*": {
      "surface_crack": "PARTIAL",
      "scratch_or_gouge": "FULL"
    }
  },
  "item_level_fallback": "COMP-HOUSING-*",
  "default_coverage": "NONE"
}
```

The matrix says what the control point is physically configured to assess; an event's reported scope cannot expand it. `item_level_fallback` explicitly selects the capability row used when product structure is unavailable and an observation has no component ID. `mode: "TARGET_ONLY"` is reserved for post-rework inspection and additionally requires the linked NCR defect/component key.

## Revision pinning

Registration selects an explicitly requested revision or the route's then-active revision. `Item.route_revision_id` is thereafter fixed. Activation is a fresh-session critical action with audit; activated historical revision content is protected by a database trigger.
