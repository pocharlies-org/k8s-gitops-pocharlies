# SC-3961: proposed company-runtime release caller

Review request: SC-4004 (Security), implementing SC-3961. Not authorized or runnable
as a release yet. No secrets, robot permissions or GitOps state change in this PR.

## What is proposed

`templates/ci/release-company-runtime.yml` is a caller for installation in
`x86-host-runtime-pocharlies/.github/workflows/` AFTER reviewing and merging the
optional extension to `reusable-release.yml`. The template now references the existing
proposal commit `5ef9168b5af1af59348164569aedbf45b33a92ea`, not an invalid zero pin.
That is NOT an approved release reference: replace it with the approved merged commit
in the separate runtime installation PR, never a mutable branch. The runtime turn
was expired at the latest check, but no owner approval or Security verdict exists,
so there is no approved merged SHA to install. This PR does not install the caller
in any execution repository.

Only manual dispatch from runtime `main` is supported, with no user inputs. The image
set is exactly `homelab/company-runtime`; no alternate registry/context/destination
or arbitrary smoke command. The release does not deploy or modify the queue/x86.

The context job uses the existing `container/prepare.py` to export committed runtime,
pinned roles/harness and the checksum-verified accounts artifact. A same-run Actions
artifact transfers a tar archive to preserve executable modes, retained for one day.
The receiving release rejects links/special/traversal entries, checks runtime SHA
and packaging/runtime bytes against its checkout BEFORE registry login, then builds.
The main preparation job remains trusted for private dependency provenance: its
`prepare.py`/`claude_vsix.py` validation and the reviewed main workflow are part of
this boundary. A hash in release.json alone is not independent attestation.

## Image identity and repeated checks

The existing reusable accepts build contexts, NOT an arbitrary local OCI image.
It therefore cannot publish the previous local candidate byte-for-byte. It rebuilds
from the committed context, adds source/revision labels, and obtains a NEW digest.
Do not reuse the local scan or claim the digest equals `bdc7702...`.

On the fresh-build path the EXACT loaded candidate passes the existing complete
Trivy vulnerability/secret gate and SBOM generation, followed by the fixed
credential-free `container/smoke.py` against its immutable local ID, BEFORE the first
candidate push. A failing scan/smoke exits without pushing that candidate. No scan
suppressions are added. Existing verified retry reuse, OIDC signing, SPDX/SLSA
attestations, exact caller/revision verification and atomic promotion remain intact.

After authorized execution, collect release evidence and `release_images`, verify
Harbor's remote digest and signatures/attestations, and compare them to the proposed
GitOps pin. No GitOps activation until final Security/CI approvals. The smoke runs
without network, capabilities, caller HOME or credentials; it is not a Claude login
or Kubernetes execution test.

## Required decisions/access (not provisioned by this PR)

- Channel owner: repository administrator `pocharlies` (verified collaborator admin;
  no CODEOWNERS file found). Request review on the framework PR and Security verdict
  through SC-4004. A reviewer request is not approval.
- Harbor identity: existing approved CI publisher needs push/pull for ONLY
  `homelab/company-runtime`, plus artifact tag/signature/attestation operations used
  by the established release. Confirm the existing robot's effective scope with the
  owner; do not broaden `robot$k8s-runtime-pull-202610` or copy its credentials.
- `HARBOR_USER`/`HARBOR_PASSWORD`: explicitly referenced only by the release job,
  never the context job/artifact. These secrets must already be approved/available
  for the caller repository; absence fails closed. No new values or permissions set.
- `FRAMEWORK_REPO_TOKEN`: existing approved read identity for `company-roles` and
  `claude-harness` contents, and Actions read on `claude-account-switcher` for its
  pinned release artifact. No PAT fallback. Confirm preexisting access; provisioning
  or broadening it is OUTSIDE this PR and requires a separate explicit authorization.
- GitHub permissions stay `contents: read`; the release job alone requests
  `id-token: write` as required by the existing keyless signing contract. This is a
  proposal for review, not a repository/org permission setting change. No write,
  admin, cluster permissions, new token or long-lived signing key.

## Validation status

Four new contract tests execute the caller guard and check fixed destination,
credential separation, same-run artifact handling and scan -> smoke -> push order.
Supply-chain, immutable workflow and release-linkage static checks pass locally.
Existing retry tests pass. Full linkage suite on this host has three environment
failures because Git 2.39 lacks `git archive --mtime`; these assertions are unchanged.
Python 3.11 also lacks the test suite's safe tar extraction API; use Python 3.12+
and pinned PyYAML in a disposable environment. CI must validate the final PR head.

This PR does not assert a successful pipeline run: final reusable SHA, installed
caller, approved credentials, Security verdict and published digest remain pending.
