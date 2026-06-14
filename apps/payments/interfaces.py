"""
Payment provider abstractions.

PaymentProviderInterface is the single seam between the booking system and
any payment processor.  StripeService implements it today; swapping in
PayPal, Square, or a manual bank-transfer flow only requires a new class
that implements this interface — no view or service code changes.

DTOs here are frozen dataclasses: plain Python, no Django, fully testable.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


class WebhookSignatureError(Exception):
    """Raised by parse_webhook() when the signature cannot be verified."""


class RefundError(Exception):
    """Raised by create_refund() when the provider rejects the refund."""


@dataclass(frozen=True)
class PaymentSession:
    """Result of creating a payment session with a provider."""
    redirect_url: str          # Where to send the customer
    provider_session_id: str   # Provider's own reference (e.g. Stripe cs_...)


@dataclass(frozen=True)
class RefundResult:
    """Result of issuing a refund."""
    refund_id: str          # re_xxx
    amount_pence: int       # actual amount refunded
    status: str             # succeeded | pending | failed


@dataclass(frozen=True)
class PaymentEvent:
    """
    Provider-agnostic representation of a completed payment.

    Produced by parse_webhook() when the provider confirms payment.

    Two IDs because payment systems distinguish them:
      provider_event_id   — the webhook event (evt_... in Stripe) — idempotency key.
      payment_intent_id   — the charge/intent (pi_... in Stripe) — stored on
                            the Order for dispute resolution and reconciliation.
    """
    order_reference: str       # UUID linking back to our Order
    amount_pence: int          # In pence (e.g. 4500 = £45.00)
    currency: str              # ISO 4217 upper-case (e.g. "GBP")
    provider_event_id: str     # Webhook event ID — idempotency key
    payment_intent_id: str     # Charge/transaction ID
    raw_payload: Any           # Full provider payload — audit trail


class PaymentProviderInterface(ABC):
    """
    Contract every payment provider must satisfy.

    Three responsibilities:
      1. Create a payment session (redirect URL for the customer)
      2. Parse + verify an inbound webhook into a PaymentEvent
      3. Issue refunds
    """

    @abstractmethod
    def create_payment_session(
        self,
        *,
        amount_pence: int,
        currency: str,
        product_name: str,
        order_reference: str,
        success_url: str,
        cancel_url: str,
        customer_email: str = "",
        expires_at: Optional[int] = None,
    ) -> PaymentSession:
        """Create a hosted payment page and return the redirect URL."""

    @abstractmethod
    def create_refund(
        self,
        *,
        payment_intent_id: str,
        amount_pence: Optional[int] = None,
        reason: str = "requested_by_customer",
    ) -> RefundResult:
        """
        Issue a refund against a previously captured payment.

        amount_pence: None → full refund; integer → partial refund.
        Raises: RefundError on failure.
        """

    @abstractmethod
    def parse_webhook(
        self,
        body: bytes,
        headers: dict,
    ) -> Optional[PaymentEvent]:
        """
        Verify signature and parse a webhook payload.

        Returns:
            PaymentEvent  — payment succeeded, ready to confirm order.
            None          — valid signature but unhandled event type.

        Raises:
            WebhookSignatureError — signature is invalid; caller returns 400.
        """

    @abstractmethod
    def retrieve_completed_session(self, session_id: str) -> Optional[PaymentEvent]:
        """
        Look up a provider session by ID and return a PaymentEvent if it has
        been paid, or None if payment is not complete or the session is unknown.

        Used as a webhook fallback on the success page — called when the
        webhook may not have fired yet.
        """
