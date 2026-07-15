.metadata.annotations as $a
| if $a["operations.pocharlies.org/state-writer-lease"] != "active"
  then error("writer lease is not active") else . end
| if (($a["operations.pocharlies.org/approved-revision"] // "")
      | test("^[0-9a-f]{40}$")) | not
  then error("approved revision is invalid") else . end
| if (($a["operations.pocharlies.org/approval-id"] // "")
      | test("^[a-z0-9][a-z0-9-]{7,63}$")) | not
  then error("approval id is invalid") else . end
| if (($a["operations.pocharlies.org/approval-sequence"] // "")
      | test("^[0-9]{14}$")) | not
  then error("approval sequence is invalid") else . end
| if ($a["operations.pocharlies.org/approved-prune"] != "true"
      and $a["operations.pocharlies.org/approved-prune"] != "false")
  then error("approved prune decision is invalid") else . end
| if has("operation")
  then error("an operation is already present") else . end
| if ((.metadata.resourceVersion // "") | test("^[0-9]+$")) | not
  then error("resourceVersion is missing or invalid") else . end
| if (.spec.syncPolicy.syncOptions | type) != "array"
  then error("GitOps syncOptions are missing or invalid") else . end
| ((.status? // {}) | has("operationState")) as $has_previous_state
| (.status.operationState.phase? // null) as $previous_phase
| if ($has_previous_state
      and (["Succeeded", "Failed", "Error"] | index($previous_phase)) == null)
  then error("previous operationState is not terminal") else . end
| {
    metadata: {
      resourceVersion: .metadata.resourceVersion
    },
    operation: {
      sync: {
        revision: $a["operations.pocharlies.org/approved-revision"],
        prune: ($a["operations.pocharlies.org/approved-prune"] == "true"),
        syncOptions: .spec.syncPolicy.syncOptions
      },
      info: [
        {
          name: "approval-id",
          value: $a["operations.pocharlies.org/approval-id"]
        },
        {
          name: "approval-sequence",
          value: $a["operations.pocharlies.org/approval-sequence"]
        }
      ]
    },
    status: {
      operationState: null
    }
  }
