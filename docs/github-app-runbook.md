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
| Actions | Read and write | Required for `workflow_dispatch` of `build.yml`; read-only cannot dispatch. Write also allows cancel/rerun and log deletion, so containment relies on the three-repo install scope and registry-only credential storage |
| Issues | Read and write | Maintain the rolling Automation health issue |
| Checks | Read-only | Observe required-check results |
| Metadata | Read-only (implicit) | Mandatory for every GitHub App; cannot be removed or widened |

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

Repository-level secrets are readable by any workflow in the repo, so
they do not enforce the coordinator-only boundary. Store the
credentials on a dedicated GitHub environment instead:

1. In `numan-cli/numan-registry` → **Settings → Environments**, create
   an environment named `automation` restricted to the default
   branch (`main`). No reviewer requirement; the protection is that
   only jobs declaring `environment: automation` can read its
   secrets, and only from `main`.
2. On that environment, create:

| Secret | Value |
| --- | --- |
| `NUMAN_AUTOMATION_APP_ID` | The App ID from the App settings page |
| `NUMAN_AUTOMATION_APP_PRIVATE_KEY` | Full PEM contents including `BEGIN/END` lines |

Coordinator jobs then opt in with `environment: automation`. Do not
create these secrets in `numan`, `numan-plugins`, or as
repository-level secrets anywhere.

## 4. Mint installation tokens in workflows

Coordinator jobs mint a short-lived installation token with the
token-action, pinned to the verified v3.3.0 commit:

```yaml
jobs:
  coordinate:
    runs-on: ubuntu-latest
    environment: automation
    steps:
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

Run once from a workstation with `gh` authenticated as an org admin.
Replace `INSTALLATION_ID` with the value recorded in section 2:

```bash
# Installation record for this App specifically (all org apps are returned;
# filter by slug or this reports other apps too)
gh api /orgs/numan-cli/installations \
  --jq '.installations[] | select(.app_slug=="numan-update-automation") | {id, repository_selection, permissions}'

# Repositories reachable by the installation. Use the org-admin endpoint:
# /installation/repositories itself requires an installation access token
# minted by the App, so it cannot be called with an admin PAT. If this
# endpoint 404s under your credential, the equivalent UI check is the App's
# Install -> Configure page, which lists the selected repositories.
gh api /orgs/numan-cli/installations/INSTALLATION_ID/repositories \
  --jq '.repositories[].full_name'
```

Expected: `repository_selection: "selected"`, the three repositories
listed, and permissions showing the five granted scopes plus the
mandatory implicit `metadata: read`. Anything beyond those six is an
over-grant; fix the App permissions before proceeding.

Inside a coordinator job the minted installation token can also call
`gh api /installation/repositories` directly; the org-admin endpoint
above is the offline equivalent.

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

The App settings token-revocation control does not revoke installation
access tokens, and rotating the private key leaves already-minted
tokens valid until they expire (up to about an hour). For immediate
disablement use suspension or uninstallation:

- **Immediate stop, reversible**: suspend the installation — org
  Settings → GitHub Apps → `numan-update-automation` → *Suspend* (or
  `gh api -X PUT /app/installations/INSTALLATION_ID/suspended`
  authenticated as the App). A suspended installation's API access is
  rejected at once, including existing tokens; unsuspending restores
  it without reconfiguration.
- **Full disable**: uninstall the App from the org (Settings →
  GitHub Apps → `numan-update-automation` → *Uninstall*). All
  installation access ends permanently.
- Report the incident on the Automation health issue
  (numan-cli/numan-registry#94) with the action taken and timeline.

## Status

Tracked in numan-cli/numan-registry#94 under rollout blockers. The
coordinator workflows that consume these credentials are Phase 3+
work; nothing in the repository references the App until they land.
