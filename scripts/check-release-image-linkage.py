#!/usr/bin/env python3
"""Fail-closed contract joining verified image digests to promoted manifests."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / ".github/workflows/reusable-release.yml"
MANIFEST_PATH = ROOT / ".github/workflows/reusable-manifest-pr-release.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(release: str, manifest: str) -> None:
    release_markers = [
        "outputs:\n      release_images:",
        "value: ${{ jobs.release.outputs.release_images }}",
        "release_images: ${{ steps.publish.outputs.release_images }}",
        "id: publish",
        "verified release evidence is empty",
        "release evidence contains an invalid or duplicate image",
        "release-images.json",
        'echo "release_images<<RHO_RELEASE_IMAGES"',
    ]
    for marker in release_markers:
        require(marker in release, f"missing release linkage output: {marker}")
    require(
        release.index('verify_harbor_tag_on_digest \\\n')
        < release.index('echo "release_images<<RHO_RELEASE_IMAGES"'),
        "release image output is emitted before final Harbor verification",
    )

    manifest_markers = [
        "image_promotions:",
        "image_targets:",
        "required: true",
        "manifest_only:",
        "Reusable manifest workflow must be called by immutable commit SHA",
        "Stamp and verify exact release image digests",
        "image target names must exactly match released image names",
        "promotion is not bound to this release",
        "bounded path array",
        "Kustomize target is not an overlay",
        "Helm target is not a chart",
        "source_path must not contain tracked symlinks",
        "source_path must not contain gitlinks or submodules",
        "Runner-local Git info attributes are forbidden for manifest releases",
        'GIT_ATTR_NOSYSTEM=1 git -c core.attributesFile=/dev/null -c tar.umask=0022 archive \\\n',
        "is forbidden for archived source file",
        "must not contain symlink components",
        "image releases require non-empty promotions and exact targets",
        "manifest_only is restricted to the central source-bound self-release",
        "Verify deployment registry digest aliases",
        'oras resolve "${repository}@${digest}"',
        "rendered image linkage mismatch",
        r"line.match(/^\s*(?:-\s*)?image:",
        "rho-release-linkage.v1",
        "imageDigestSetSha256",
        'patched_tree_sha="$(git write-tree)"',
        '"$PATCHED_TREE_SHA" \\\n              -- "$SOURCE_PATH"',
        '-C "$staged_source" .',
        "umask 022",
        "tar --extract --same-permissions",
        "rho.skirmshop.es/patched-tree",
        "rho.skirmshop.es/image-digest-set-sha256",
        'git read-tree --reset -u "$PATCHED_TREE_SHA"',
    ]
    for marker in manifest_markers:
        require(marker in manifest, f"missing manifest/image linkage guard: {marker}")

    stamp = manifest.index("Stamp and verify exact release image digests")
    build = manifest.index("Build exact patched manifest bundle")
    publish = manifest.index("Publish Argo CD OCI manifest bundle")
    archive = manifest.index(
        "          GIT_ATTR_NOSYSTEM=1 git -c core.attributesFile=/dev/null -c tar.umask=0022 archive \\",
    )
    reset_source = manifest.index('git read-tree --reset -u "$SOURCE_SHA"')
    reset_patched = manifest.index('git read-tree --reset -u "$PATCHED_TREE_SHA"')
    require(
        stamp < build < archive < publish < reset_source < reset_patched,
        "patched-tree release order is invalid",
    )
    require(
        manifest.count('git read-tree --reset -u "$PATCHED_TREE_SHA"') == 1,
        "promotion must consume exactly one patched tree",
    )
    require(
        'git read-tree --reset -u "$SOURCE_SHA"\n          git config' not in manifest,
        "promotion still commits the unstamped source tree",
    )
    require("eval " not in manifest and "yq eval" not in manifest, "target-controlled expression evaluation is forbidden")
    require("setExistingPath" in manifest, "Helm updates must use bounded path arrays")
    require("kustomize edit set image" in manifest, "Kustomize digest stamping is absent")
    require("helm template rho-release" in manifest, "Helm digest rendering is not verified")
    require(
        'GIT_ATTR_NOSYSTEM=1 git -c core.attributesFile=/dev/null -c tar.umask=0022 archive \\\n              --format=tar'
        in manifest
        and '"$PATCHED_TREE_SHA" \\\n              -- "$SOURCE_PATH"' in manifest,
        "manifest bundle must be archived from the patched Git tree",
    )


release = RELEASE_PATH.read_text(encoding="utf-8")
manifest = MANIFEST_PATH.read_text(encoding="utf-8")
try:
    validate(release, manifest)
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

for label, mutated_release, mutated_manifest in [
    (
        "missing exact-set gate",
        release,
        manifest.replace("image target names must exactly match released image names", "target mismatch ignored", 1),
    ),
    (
        "source tree promoted",
        release,
        manifest.replace('git read-tree --reset -u "$PATCHED_TREE_SHA"', 'git read-tree --reset -u "$SOURCE_SHA"', 1),
    ),
    (
        "unverified release output",
        release.replace('verify_harbor_tag_on_digest \\\n', 'true # verification removed\n', 1),
        manifest,
    ),
    (
        "symlink guard removed",
        release,
        manifest.replace("source_path must not contain tracked symlinks", "symlinks allowed", 1),
    ),
    (
        "source tree archive",
        release,
        manifest.replace('"$PATCHED_TREE_SHA" \\\n              -- "$SOURCE_PATH"', '"$SOURCE_SHA" \\\n              -- "$SOURCE_PATH"', 1),
    ),
    (
        "empty image bypass",
        release,
        manifest.replace(
            "image releases require non-empty promotions and exact targets",
            "empty image linkage accepted",
            1,
        ),
    ),
    (
        "kustomize list image parser",
        release,
        manifest.replace(r"(?:-\s*)?image:", r"image:", 1),
    ),
    (
        "runner-local archive attributes",
        release,
        manifest.replace(
            "Runner-local Git info attributes are forbidden for manifest releases",
            "runner-local attributes accepted",
            1,
        ),
    ),
    (
        "archive permission preservation",
        release,
        manifest.replace("tar --extract --same-permissions", "tar --extract", 1),
    ),
]:
    try:
        validate(mutated_release, mutated_manifest)
    except (ValueError, ValueError):
        continue
    raise SystemExit(f"linkage mutation self-test unexpectedly passed: {label}")

# Revisado el 18-10-2026 (SC-2685): en los dos workflows solo entran los tres secretos
# del notificador en `on.workflow_call.secrets` (ya se usaban, no estaban declarados y
# se resolvian vacios). El enlace digest de imagen -> manifest no cambia.
# Revisado el 18-10-2026 (SC-2749): en el release workflow entran la caché de buildx
# por registry (`<image>:buildcache`, la escribe solo el release) y la extraccion de la
# instalacion verificada de Buildx a `.github/actions/setup-buildx` (digest pinneado en
# check-release-supply-chain.py). El enlace digest de imagen -> manifest no cambia.
# SC-2749 bis: la referencia a la accion pasa a ruta absoluta @main (el './' dentro de
# un reusable apunta al repo que llama).
# Revisado el 28-10-2026 (SC-2856): el gate Trivy del release, cuando falla, imprime sus
# hallazgos bloqueantes antes de salir con 1 (el informe va a fichero y el step moria con
# exit 1 sin nombrar nada). El enlace digest de imagen -> manifest no cambia.
# Revisado el 29-10-2026 (SC-2888): lo unico que cambia en el workflow es el env del job
# TRIVY_DB_REPOSITORY (mirror.gcr.io da BLOB_UNKNOWN al blob actual de trivy-db desde el
# egreso ARC; se punta al espejo oficial de ECR). El enlace digest de imagen -> manifest
# no cambia.
expected_release_sha256 = "52986835bf7baf565224971f8d1641e811efb49d72111bd751d33decdcc3b1e2"
expected_manifest_sha256 = "daafcd9d938a6accdcb14de3659dfd9dd983f0a6b8505d5764076565cdfbe405"
release_sha256 = hashlib.sha256(release.encode()).hexdigest()
manifest_sha256 = hashlib.sha256(manifest.encode()).hexdigest()
require(release_sha256 == expected_release_sha256, f"release linkage workflow changed: {release_sha256}")
require(manifest_sha256 == expected_manifest_sha256, f"manifest linkage workflow changed: {manifest_sha256}")

print("Release-to-manifest image digest linkage contract passed")
