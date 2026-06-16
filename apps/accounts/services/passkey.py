"""
Passkey (WebAuthn) service — wraps py_webauthn for registration and authentication.

RP_ID must match the domain of WEBAUTHN_ORIGIN exactly.
Dev: rp_id="localhost", origin="http://localhost:8000"
Prod: rp_id="reachswim.com", origin="https://reachswim.com"
"""
from django.conf import settings

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

RP_ID = getattr(settings, "WEBAUTHN_RP_ID", "localhost")
RP_NAME = getattr(settings, "WEBAUTHN_RP_NAME", "ReachSwim")
ORIGIN = getattr(settings, "WEBAUTHN_ORIGIN", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def generate_registration_options(user):
    """
    Build registration options for a logged-in user adding a new passkey.
    Uses resident keys (discoverable credentials) so login needs no username.
    """
    return webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user.pk).encode(),
        user_name=user.email,
        user_display_name=user.full_name or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )


def verify_registration(credential_json: str, challenge_bytes: bytes):
    """
    Verify a registration response from the browser.
    Returns the webauthn VerifiedRegistration object on success.
    Raises on failure.
    """
    import json
    return webauthn.verify_registration_response(
        credential=json.loads(credential_json),
        expected_challenge=challenge_bytes,
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
        require_user_verification=True,
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def generate_authentication_options():
    """
    Build authentication options with no allowed_credentials list.
    The browser shows all matching passkeys from its own store (discoverable).
    No username needed upfront — avoids user enumeration.
    """
    return webauthn.generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )


def verify_authentication(
    credential_json: str,
    challenge_bytes: bytes,
    stored_public_key: bytes,
    stored_sign_count: int,
):
    """
    Verify an authentication assertion from the browser.
    Returns the webauthn VerifiedAuthentication object (has .new_sign_count).
    Raises on any failure.
    """
    return webauthn.verify_authentication_response(
        credential=credential_json,
        expected_challenge=challenge_bytes,
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
        credential_public_key=bytes(stored_public_key),
        credential_current_sign_count=stored_sign_count,
        require_user_verification=True,
    )
