# Configurable routes

Routes are stored as `RouteDefinition → RouteRevision → RouteStep[]`; no route is hardcoded into replay. A step may carry a `ControlPointPolicy` reference through:

```text
control_point_id, operation_id, required, inspection_scope, trust_policy_id
```

The technologist can create/import a route, clone its ordered step array into a new draft revision, edit JSON, activate it, and export the resulting structure. The UI intentionally uses ordered JSON rather than drag-and-drop.

Activation makes the revision immutable and supersedes the former active revision. Registration resolves the active revision once and stores it on the item. Later route changes do not alter an already started item.

If a following route operation starts without the required preceding inspection, replay adds `MISSING_CHECK` as analysis limitation. It never fabricates an inspection event.
