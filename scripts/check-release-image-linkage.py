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
        'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}:${SOURCE_PATH}")"',
        'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}^{tree}")"',
        'git archive \\\n',
        "rho.skirmshop.es/patched-tree",
        "rho.skirmshop.es/image-digest-set-sha256",
        'git read-tree --reset -u "$PATCHED_TREE_SHA"',
    ]
    for marker in manifest_markers:
        require(marker in manifest, f"missing manifest/image linkage guard: {marker}")

    stamp = manifest.index("Stamp and verify exact release image digests")
    publish = manifest.index("Publish Argo CD OCI manifest bundle")
    archive = manifest.index("          git archive \\")
    reset_source = manifest.index('git read-tree --reset -u "$SOURCE_SHA"')
    reset_patched = manifest.index('git read-tree --reset -u "$PATCHED_TREE_SHA"')
    require(
        stamp < publish < archive < reset_source < reset_patched,
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
        'git archive \\\n            --format=tar' in manifest,
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
        manifest.replace(
            'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}:${SOURCE_PATH}")"',
            'source_tree_sha="$(git rev-parse "${SOURCE_SHA}:${SOURCE_PATH}")"',
            1,
        ),
    ),
    (
        "root source tree archive",
        release,
        manifest.replace(
            'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}^{tree}")"',
            'source_tree_sha="$(git rev-parse "${SOURCE_SHA}^{tree}")"',
            1,
        ),
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
]:
    try:
        validate(mutated_release, mutated_manifest)
    except (ValueError, ValueError):
        continue
    raise SystemExit(f"linkage mutation self-test unexpectedly passed: {label}")

expected_release_sha256 = "f3e1ef0fffce37d657308f64308a580f6c5b48ecc4aceea39a1232fd97724cb0"
expected_manifest_sha256 = "b686b3222fe2882019deede58c73ab504564cd2e322c5c1ee30f5c0be38e8946"
release_sha256 = hashlib.sha256(release.encode()).hexdigest()
manifest_sha256 = hashlib.sha256(manifest.encode()).hexdigest()
require(release_sha256 == expected_release_sha256, f"release linkage workflow changed: {release_sha256}")
require(manifest_sha256 == expected_manifest_sha256, f"manifest linkage workflow changed: {manifest_sha256}")

print("Release-to-manifest image digest linkage contract passed")
