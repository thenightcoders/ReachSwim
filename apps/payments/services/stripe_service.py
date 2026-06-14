"""
StripeService — implements PaymentProviderInterface for Stripe Checkout.

One class, one responsibility: translate between Stripe's API and the
provider-agnostic interface.  No Django ORM.  No booking logic.

Ported from Jetski, adapted for GBP / pence and order_reference.
"""
from typing import Optional

import stripe
from django.conf import settings

from apps.payments.interfaces import (
    PaymentEvent,
    PaymentProviderInterface,
    PaymentSession,
    RefundError,
    RefundResult,
    WebhookSignatureError,
)

_CHECKOUT_COMPLETED = "checkout.session.completed"


class StripeService(PaymentProviderInterface):

    def __init__(self) -> None:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    # ------------------------------------------------------------------
    # PaymentProviderInterface
    # ------------------------------------------------------------------

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
        """Create a Stripe Checkout session and return the redirect URL."""
        params: dict = {
            "payment_method_types": ["card"],
            "submit_type": "book",
            "line_items": [
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {"name": product_name},
                        "unit_amount": amount_pence,
                    },
                    "quantity": 1,
                }
            ],
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"order_reference": order_reference},
            "payment_intent_data": {"description": product_name},
        }
        if customer_email:
            params["customer_email"] = customer_email
        if expires_at is not None:
            params["expires_at"] = expires_at
        session = stripe.checkout.Session.create(**params)
        return PaymentSession(
            redirect_url=session.url,
            provider_session_id=session.id,
        )

    def create_refund(
        self,
        *,
        payment_intent_id: str,
        amount_pence: Optional[int] = None,
        reason: str = "requested_by_customer",
    ) -> RefundResult:
        """Issue a refund against a PaymentIntent."""
        params: dict = {
            "payment_intent": payment_intent_id,
            "reason": reason,
        }
        if amount_pence is not None:
            params["amount"] = amount_pence
        try:
            refund = stripe.Refund.create(**params)
        except stripe.error.StripeError as exc:
            raise RefundError(str(exc)) from exc
        return RefundResult(
            refund_id=refund.id,
            amount_pence=refund.amount,
            status=refund.status,
        )

    def parse_webhook(
        self,
        body: bytes,
        headers: dict,
    ) -> Optional[PaymentEvent]:
        """
        Verify Stripe signature and extract a PaymentEvent.

        Returns None for event types we don't handle.
        Raises WebhookSignatureError on bad signature.
        """
        sig = headers.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(
                body, sig, settings.STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError as exc:
            raise WebhookSignatureError(str(exc)) from exc

        if event["type"] != _CHECKOUT_COMPLETED:
            return None

        session = event["data"]["object"]

        order_ref = session.get("metadata", {}).get("order_reference")
        if not order_ref:
            return None

        return PaymentEvent(
            order_reference=order_ref,
            amount_pence=session["amount_total"],
            currency=session.get("currency", "gbp").upper(),
            provider_event_id=event["id"],
            payment_intent_id=session.get("payment_intent", ""),
            raw_payload=event,
        )

    def retrieve_completed_session(self, session_id: str) -> Optional[PaymentEvent]:
        """
        Retrieve a Checkout session from Stripe and return a PaymentEvent if
        it has been paid, or None if unpaid / unknown.

        Uses a synthetic provider_event_id so the checkout service can call
        confirm_order() idempotently (it deduplicates on that field).
        """
        if not session_id or session_id.startswith("{"):
            return None
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.StripeError:
            return None

        if session.payment_status != "paid":
            return None

        order_ref = (session.metadata or {}).get("order_reference")
        if not order_ref:
            return None

        return PaymentEvent(
            order_reference=order_ref,
            amount_pence=session.amount_total,
            currency=(session.currency or "gbp").upper(),
            provider_event_id=f"success_{session.id}",
            payment_intent_id=session.payment_intent or "",
            raw_payload={"session_id": session_id},
        )

