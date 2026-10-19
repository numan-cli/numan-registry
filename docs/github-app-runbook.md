# Numan automation GitHub App — provisioning runbook

The unattended update pipeline uses a dedicated GitHub App for bot
identity: PR creation, branch pushes, issue comments, and workflow
dispatch. `GITHUB_TOKEN` cannot trigger downstream workflows on bot
pushes, so App installation tokens are required for unattended CI.
This document is the provisioning, verification, rotation, and
revocation procedure. It is executed once by an org admin.

## Trust boundary

- The App is installed on exactly three repositories: `numan`,
  `numan-plugins`, `numan-registry`.
- App credentials live only in `numan-registry` coordinator jobs.
  Build and test jobs in `numan-plugins` and `numan` never receive the
  App private key, installation tokens, or signing secrets.
- The App gets no administration, workflow-editing, or
  branch-protection bypass capability. If a future need requires a
  wider scope, it is a new reviewed change, not an edit of this App.

## 1. Create the App

Org admin: <https://github.com/organizations/numan-cli/settings/apps/new>

| Field | Value |
| --- | --- |
| GitHub App name | `numan-update-automation` |
| Homepage URL | `https://github.com/numan-cli/numan-registry` |
| Webhook | Disabled (coordinator is job-driven; enable later only if event-driven reconciliation is adopted) |
| Where can this App be installed? | Only on this account |

### Repository permissions

| Permission | Access | Why |
| --- | --- | --- |
| Contents | Read and write | Create/update bot branches, ledger commits |
| Pull requests | Read and write | Open and reconcile update/intake PRs |
| Actions | Read and write | Dispatch `build.yml`, read run state |
| Issues | Read and write | Maintain the rolling Automation health issue |
| Checks | Read-only | Observe required-check results |

Explicitly **not** granted: Administration, Workflows (workflow file
edits), Secrets, Environments, Members, or any organization-level
permission. Leave everything else at "No access".

## 2. Install the App

From the App settings page: **Install App** → select the
`numan-cli` org → **Only select repositories** → `numan`,
`numan-plugins`, `numan-registry`.

Record the installation ID (visible in the resulting URL:
`…/settings/installations/<id>`).

## 3. Store credentials (registry coordinator only)

Generate a private key in App settings (**Private keys** →
*Generate a private key*). The PEM downloads once; do not commit it.

In `numan-cli/numan-registry` → **Settings → Secrets and variables →
Actions**, create:

| Secret | Value |
| --- | --- |
| `NUMAN_AUTOMATION_APP_ID` | The App ID from the App settings page |
| `NUMAN_AUTOMATION_APP_PRIVATE_KEY` | Full PEM contents including `BEGIN/END` lines |

Do not create these secrets in `numan` or `numan-plugins`. Do not
place them in environment-level secrets unless the environment is the
trusted coordinator scope.

## 4. Mint installation tokens in workflows

Coordinator jobs mint a short-lived installation token with the
token-action, pinned to the verified v3.3.0 commit:

```yaml
- uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510 # v3.3.0
  id: app-token
  with:
    app-id: ${{ secrets.NUMAN_AUTOMATION_APP_ID }}
    private-key: ${{ secrets.NUMAN_AUTOMATION_APP_PRIVATE_KEY }}
    owner: numan-cli
    repositories: numan-registry,numan-plugins,numan
- run: gh pr create ...
  env:
    GH_TOKEN: ${{ steps.app-token.outputs.token }}
```

Installation tokens expire after one hour and carry exactly the App's
installed permission set. Bot pushes made with them trigger downstream
workflows, which is why `GITHUB_TOKEN` is unsuitable for this role.
Reference: [GitHub App authentication in Actions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow).

## 5. Verify after provisioning

Run once from a workstation with `gh` authenticated as an org admin:

```bash
# Installation exists on exactly the three repositories
gh api /orgs/numan-cli/installations --jq '.installations[] | {id, app_id, repository_selection}'

# Repositories reachable by the installation (requires an installation token)
gh api /installation/repositories --jq '.repositories[].full_name'

# Permissions match the table above
gh api /orgs/numan-cli/installations --jq '.installations[].permissions'
```

Expected: `repository_selection: "selected"`, the three repositories
listed, and permissions showing only the five granted scopes.

## 6. Rotation

1. App settings → **Private keys** → *Generate a private key*.
2. Update `NUMAN_AUTOMATION_APP_PRIVATE_KEY` in
   `numan-cli/numan-registry` Actions secrets.
3. Confirm a coordinator run succeeds (manual dispatch of the
   coordinator workflow once it exists, or a `gh api` smoke call with a
   token minted locally).
4. Delete the old private key in App settings.

Tokens already minted expire within an hour; no other cleanup needed.

## 7. Revocation / emergency disable

- **Cut pipeline authority without deleting the App**: rotate the
  private key (section 6) and revoke all installation tokens via
  App settings → **Advanced → Revoke all tokens**.
- **Full disable**: uninstall the App from the org (Settings →
  Third-party Access → GitHub Apps → numan-update-automation →
  Uninstall). All installation tokens die immediately.
- Report the incident on the Automation health issue
  (numan-cli/numan-registry#94) with the action taken and timeline.

## Status

Tracked in numan-cli/numan-registry#94 under rollout blockers. The
coordinator workflows that consume these credentials are Phase 3+
work; nothing in the repository references the App until they land.
