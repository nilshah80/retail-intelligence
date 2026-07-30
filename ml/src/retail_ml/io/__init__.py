"""Verified, read-only access to curated forecast inputs."""

from retail_ml.io.bundle import (
    BundleVerificationError,
    InputBundle,
    InputBundlePaths,
    VerifiedInputBundle,
    discover_input_bundle,
)

__all__ = [
    "BundleVerificationError",
    "InputBundle",
    "InputBundlePaths",
    "VerifiedInputBundle",
    "discover_input_bundle",
]
