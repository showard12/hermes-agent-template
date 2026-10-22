# Unattended Pantryfy reviews

The `github-pr-review` route uses the `pantryfy_review` toolset. Its single
`pantryfy_pr_read` tool retrieves PR metadata, paginated changed files and
patches, committed source at the current head/base, CI checks and comments.
The existing GitHub App wrapper supplies authentication. The reader only
issues fixed `GET` requests to `showard12/pantry_app`; it accepts neither shell
commands, arbitrary URLs, local file paths nor write operations.

Previously the route exposed `terminal`. Routine Python inspection wrappers
triggered Hermes's command guard, and unattended webhook sessions timed out
waiting for `/approve`. Do not fix this by disabling approvals globally.
The dedicated reader needs no command approval and does not run PR code on
the credential-bearing gateway. Runtime execution remains in CI. Reviews
must disclose any missing CI evidence or unreadable/truncated source.

`start.sh` installs the plugin and matching review skill from the image on
each boot, and `configure_github_webhook.py` enables the plugin and selects
it for this route. Other platform toolsets and approval settings are unchanged.
The route retains the signed webhook, repository/action/draft filters,
coalescing and `github_comment` delivery. The model returns a final review;
the adapter publishes it, so the model does not need comment-write tools.

Evidence reads require the exact head returned by `metadata`. Mutable diff
reads are checked again afterward; a force-push fails the read rather than
silently mixing revisions. The reviewer rechecks the head before finalizing.
This is a static review with CI evidence, not arbitrary local code execution.

## Validation

Run `python -m unittest discover -s tests -v` (requires PyYAML) and
`bash -n start.sh`. On the pinned Hermes runtime, discover plugins and resolve
the webhook's toolsets through `_get_platform_tools` and
`get_tool_definitions`. The resulting model tool list must contain only
`pantryfy_pr_read`. Verify metadata/files/source/checks against a real PR
without starting a model call. Confirm existing approval settings and webhook
secret are unchanged and gateway health returns after restart/deployment.

To test delivery end to end, observe the next normal eligible PR event. A
manual redelivery starts a paid review and must be deliberate; do not repeat
one already in progress. Inspect its final comment and session tool calls
for completion without an approval wait. API-read validation alone is not
proof of a completed model review.

## Rollback

Restore the previous route, skill and plugin configuration from the private
configuration backup, then restart an idle gateway. Returning the route to
`terminal` restores the old approval-dependent behavior. Never roll back
credentials or global security policy. Preserve the incident evidence.
