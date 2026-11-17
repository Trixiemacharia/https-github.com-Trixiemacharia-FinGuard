"""Interface stub for a hosted KYC provider (e.g. Smile ID, Onfido, Veriff).

Not implemented: it needs a provider contract, API credentials and a data-processing agreement, because images
would leave this server. Selecting it makes every verification fail closed to MANUAL_REVIEW until implemented.

To implement, subclass IdentityEngine: `analyze` should call the provider's face/quality endpoint and fill
FaceAnalysis (face_count, yaw_ratio, quality metrics); `similarity` should return the provider's match score
mapped to 0..1. Keep thresholds in IDENTITY_VERIFICATION so decisions stay in apps.identity.services.
"""
from .base import EngineUnavailable, IdentityEngine


class VendorEngine(IdentityEngine):
    model_version = "vendor-unconfigured"

    def check_ready(self):
        raise EngineUnavailable("vendor_not_configured")

    def analyze(self, image_bytes, *, kind):
        raise EngineUnavailable("vendor_not_configured")

    def similarity(self, a, b):
        raise EngineUnavailable("vendor_not_configured")
