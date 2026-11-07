# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare a new local configuration bundle without copying checkpoint weights."""

import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path

from stoneglass.inference.contracts import InferenceContext, ProgressEvent, ProgressStage
from stoneglass.inference.local_process import prepare_directory
from stoneglass.inference.resource_lease import ResourceLease
from stoneglass.inference.resources import (
    CONFIG_FILES, ResourceFile, SDXLManifest, checkpoint_header, invalid, strict_local, validate_sdxl,
)


def _hash(path: Path, context: InferenceContext) -> str:
    digest = hashlib.sha256()
    size, done = path.stat().st_size, 0
    last = -1
    with path.open("rb") as source:
        while data := source.read(4 * 1024 * 1024):
            context.check_cancelled()
            digest.update(data)
            done += len(data)
            percent = done * 100 // size
            if percent != last:
                context.report_event(ProgressEvent(ProgressStage.VALIDATING, percent, "Hashing existing local resource bytes"))
                last = percent
    context.check_cancelled()
    return digest.hexdigest()


def prepare_sdxl_bundle(checkpoint: Path, source: Path, destination: Path,
                        expected_resources: Mapping[str, str], context: InferenceContext) -> Path:
    """Require reviewed resource hashes; never acquire files or overwrite a bundle.

    The checkpoint is read/hashed, not loaded as tensors or copied. Failure leaves
    any new partial directory without a readiness manifest for manual review.
    """
    context.check_cancelled()
    if set(expected_resources) != set(CONFIG_FILES) or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in expected_resources.values()
    ):
        raise invalid("Provide the reviewed SHA256 values for all 14 local configuration resources.")
    checkpoint, source = strict_local(checkpoint), strict_local(source, directory=True)
    if destination.exists():
        raise invalid("Choose a new local bundle directory; existing bundles will not be overwritten.")
    prepare_directory(destination.parent)
    source_resources = tuple(ResourceFile(name, strict_local(source / name).stat().st_size, expected_resources[name])
                             for name in CONFIG_FILES)
    required = sum(resource.bytes for resource in source_resources) * 2 + 64 * 1024 * 1024
    if shutil.disk_usage(destination.parent).free < required:
        raise invalid("Insufficient local disk space for configuration staging and a 64 MiB reserve.")
    provisional = SDXLManifest(checkpoint, checkpoint.stat().st_size, "0" * 64, source, source_resources)
    with ResourceLease(provisional):
        checkpoint_header(checkpoint)
        for resource in source_resources:
            if _hash(source / resource.path, context) != resource.sha256:
                raise invalid(f"The original reviewed configuration changed: {resource.path}.")
        digest = _hash(checkpoint, context)
        context.check_cancelled()
        destination.mkdir()  # Exclusive creation; no existing destination modified.
        strict_local(destination, directory=True)
        config = destination / "config"
        config.mkdir()
        for resource in source_resources:
            context.check_cancelled()
            target = config / resource.path
            prepare_directory(target.parent)
            with target.open("xb") as stream:
                stream.write((source / resource.path).read_bytes())
        manifest = SDXLManifest(checkpoint, provisional.checkpoint_bytes, digest, config, source_resources)
        # Independent full second pass verifies checkpoint and copied resources,
        # shapes/header/config/BPE using the same production resource validator.
        validate_sdxl(manifest, context)
        data = {"schema": 1, "architecture": "sdxl-base", "checkpoint": {
            "path": str(checkpoint), "bytes": manifest.checkpoint_bytes, "sha256": digest},
            "config_directory": str(config), "resources": [
                {"path": r.path, "bytes": r.bytes, "sha256": r.sha256} for r in source_resources]}
        context.check_cancelled()
        path = destination / "manifest.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        return path
