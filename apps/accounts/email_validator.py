"""
Standalone email validation module. No Django dependencies.

Install:
    pip install git+https://git.ksol.io/karolyi/py3-validate-email@v1.0.9

Checks (each individually toggle-able):
  check_format     — RFC-compliant address structure              (fast, no network)
  check_blacklist  — disposable / temporary domain list           (fast, no network)
  check_dns        — MX records exist for the domain              (network, ~1-3 s)
  check_smtp       — mailbox exists via SMTP handshake            (network, ~5-10 s,
                     unreliable — most servers block it; off by default)

Usage:
    result = validate_email_address("user@mailnull.com")
    if not result.valid:
        raise SomeError(result.reason)

    # With DNS check (background job / async path):
    result = validate_email_address(email, check_dns=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from validate_email import validate_email_or_fail
from validate_email.exceptions import (
    AddressFormatError,
    DomainBlacklistedError,
    EmailValidationError,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EmailCheckResult:
    """
    Return value of validate_email_address().

    valid   — True if all requested checks passed.
    reason  — Human-readable failure reason when valid=False, else None.
    checks  — Which checks were actually executed.
    """
    valid: bool
    reason: Optional[str] = None
    checks: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_email_address(
    email: str,
    *,
    check_format: bool = True,
    check_blacklist: bool = True,
    check_dns: bool = False,
    check_smtp: bool = False,
    dns_timeout: int = 5,
    smtp_timeout: int = 10,
    smtp_from_address: Optional[str] = None,
) -> EmailCheckResult:
    """
    Validate an email address.

    Args:
        email             — The address to validate.
        check_format      — Reject addresses that don't conform to RFC syntax.
        check_blacklist   — Reject known disposable / throwaway domains.
                            List is from disposable-email-domains on GitHub,
                            auto-updated by the package every 5 days.
        check_dns         — Reject domains with no valid MX records.
                            Adds network latency; keep False for synchronous web
                            request handlers, enable in background tasks.
        check_smtp        — Probe the SMTP server to verify the mailbox exists.
                            Slow and unreliable — most servers block or greylist.
                            Almost never worth enabling in production.
        dns_timeout       — DNS query timeout in seconds.
        smtp_timeout      — SMTP connection timeout in seconds.
        smtp_from_address — MAIL FROM used in the SMTP probe (defaults to email).

    Returns:
        EmailCheckResult — check .valid or use it as a bool.
    """
    checks_run = [
        name for name, enabled in [
            ("format", check_format),
            ("blacklist", check_blacklist),
            ("dns", check_dns),
            ("smtp", check_smtp),
        ] if enabled
    ]

    try:
        validate_email_or_fail(
            email_address=email,
            check_format=check_format,
            check_blacklist=check_blacklist,
            check_dns=check_dns,
            dns_timeout=dns_timeout,
            check_smtp=check_smtp,
            smtp_timeout=smtp_timeout,
            smtp_from_address=smtp_from_address,
        )
        return EmailCheckResult(valid=True, checks=checks_run)

    except AddressFormatError:
        return EmailCheckResult(
            valid=False,
            reason="Enter a valid email address.",
            checks=checks_run,
        )
    except DomainBlacklistedError:
        return EmailCheckResult(
            valid=False,
            reason="Disposable or temporary email addresses are not accepted.",
            checks=checks_run,
        )
    except EmailValidationError as exc:
        # Covers all DNSError and SMTPError subtypes
        return EmailCheckResult(
            valid=False,
            reason=_friendly_message(exc),
            checks=checks_run,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EXCEPTION_MESSAGES: dict[str, str] = {
    "DomainNotFoundError":      "That email domain doesn't exist.",
    "NoNameserverError":        "That email domain has no name server.",
    "DNSTimeoutError":          "Couldn't reach the email domain's DNS server — try again.",
    "DNSConfigurationError":    "That email domain has a misconfigured DNS.",
    "NoMXError":                "That email domain can't receive mail (no MX records).",
    "NoValidMXError":           "That email domain has no valid mail servers.",
    "AddressNotDeliverableError": "That email address doesn't exist on the mail server.",
    "SMTPCommunicationError":   "The mail server refused our connection.",
    "SMTPTemporaryError":       "Couldn't verify the address right now — try again.",
}


def _friendly_message(exc: EmailValidationError) -> str:
    return _EXCEPTION_MESSAGES.get(type(exc).__name__, str(exc) or "Email validation failed.")
