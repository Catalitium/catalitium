"""Stripe payment routes: B2C subscriptions, B2B job posting checkout, webhooks."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..helpers import csrf_valid
from ..models.db import (
    create_api_key,
    get_api_key_by_email,
    get_stripe_order,
    get_subscription_by_stripe_id,
    get_user_subscriptions,
    insert_job_posting,
    insert_stripe_order,
    logger,
    mark_stripe_order_job_submitted,
    mark_stripe_order_paid,
    sync_api_key_quota_for_api_access,
    upsert_user_subscription,
)
from ..mailer import (
    send_api_access_key_provisioned,
    send_api_access_payment_confirmed,
    send_api_key_activation_reminder,
    send_job_posting_admin_notification,
    send_job_posting_confirmation,
)

try:
    import stripe as _stripe
except ImportError:
    _stripe = None  # type: ignore[assignment]

bp = Blueprint("stripe_routes", __name__)

# ---------------------------------------------------------------------------
# B2C product catalogue
# ---------------------------------------------------------------------------
_STRIPE_B2C_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "mi_premium": {
        "price_id": os.getenv("STRIPE_PRICE_MI_PREMIUM", ""),
        "product_line": "market_intelligence",
        "tier": "premium",
        "name": "Market Intelligence Premium",
        "price_display": "$9",
        "tagline": "Full reports, complete salary benchmarks, hiring trends.",
        "features": [
            "Unlimited report access",
            "Full job board access",
            "Complete salary benchmarks",
            "Hiring trend data",
        ],
        "badge": None,
    },
    "mi_pro": {
        "price_id": os.getenv("STRIPE_PRICE_MI_PRO", ""),
        "product_line": "market_intelligence",
        "tier": "pro",
        "name": "Market Intelligence Pro",
        "price_display": "$99",
        "tagline": "Everything in Premium plus personalised reports and exports.",
        "features": [
            "Everything in Premium",
            "Personalised market intelligence reports",
            "Data exports (CSV / JSON)",
            "Priority support",
        ],
        "badge": "Best Value",
    },
    "api_access": {
        "price_id": os.getenv("STRIPE_PRICE_API_ACCESS", ""),
        "product_line": "api_access",
        "tier": "api",
        "name": "API Access",
        "price_display": "$4.99",
        "tagline": "10 000 calls/month across all endpoints.",
        "features": [
            "10 000 API calls/month",
            "All endpoints (jobs, salary, trends)",
            "Salary and trend data",
            "Standard support",
        ],
        "badge": None,
    },
}

_B2C_PRICE_TO_KEY: Dict[str, str] = {
    p["price_id"]: k for k, p in _STRIPE_B2C_PRODUCTS.items() if p["price_id"]
}

# ---------------------------------------------------------------------------
# B2B job posting products
# ---------------------------------------------------------------------------
_STRIPE_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "core_post": {
        "price_id": os.getenv("STRIPE_PRICE_CORE_POST", ""),
        "name": "Core Post",
        "tagline": "Single job listing, active for 100 days.",
        "price_display": "$109",
        "mode": "payment",
        "slots": 1,
        "badge": None,
        "features": [
            "1 job listing",
            "Active for 100 days",
            "Standard placement",
            "Email confirmation",
        ],
    },
    "premium_post": {
        "price_id": os.getenv("STRIPE_PRICE_PREMIUM_POST", ""),
        "name": "Premium Post",
        "tagline": "Top placement for 100 days.",
        "price_display": "$219",
        "mode": "payment",
        "slots": 1,
        "badge": "Most Popular",
        "features": [
            "1 job listing",
            "Active for 100 days",
            "Top placement in search",
            "Featured badge on listing",
            "Email confirmation",
        ],
    },
    "elite_plan": {
        "price_id": os.getenv("STRIPE_PRICE_ELITE_PLAN", ""),
        "name": "Elite Plan",
        "tagline": "3 featured posts per month. Cancel anytime.",
        "price_display": "$379",
        "mode": "subscription",
        "slots": 3,
        "badge": "Best Value",
        "features": [
            "3 featured job posts/month",
            "Priority placement",
            "Cancel anytime",
            "Dedicated account support",
            "Email confirmation",
        ],
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stripe_subscription_to_dict(sub_obj: Any) -> Dict[str, Any]:
    """Normalize Stripe SDK objects to plain dicts for webhook handlers."""
    if isinstance(sub_obj, dict):
        return sub_obj
    to_dict = getattr(sub_obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    try:
        return dict(sub_obj)
    except Exception:
        return {}


def _ensure_api_access_key_from_subscription(
    *,
    user_id: str,
    user_email: str,
    base_url: str,
) -> None:
    """Create an api_keys row + email raw key when none exists (paid API Access)."""
    user_email = (user_email or "").strip()
    if not user_email:
        return
    base = (base_url or os.getenv("BASE_URL", "https://catalitium.com")).rstrip("/")

    existing = get_api_key_by_email(user_email)
    if existing:
        return

    raw_key = "cat_" + secrets.token_hex(22)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    confirm_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    ok = create_api_key(
        email=user_email,
        key_hash=key_hash,
        key_prefix=key_prefix,
        confirm_token=confirm_token,
        confirm_token_expires_at=expires_at,
        created_from_ip="stripe_webhook",
        user_id=str(user_id or ""),
    )
    if not ok:
        logger.warning("api_access: create_api_key failed email=%s", user_email)
        return
    sync_api_key_quota_for_api_access(user_email, True)
    confirm_url = f"{base}/api/keys/confirm?token={confirm_token}"
    send_api_access_key_provisioned(user_email, raw_key, confirm_url)
    logger.info("api_access: key provisioned prefix=%s email=%s", key_prefix, user_email)


def _checkout_api_access_confirmation_email(user_email: str, had_active_key_before: bool) -> None:
    """Short receipt when checkout completes; skip if we already emailed a new key."""
    user_email = (user_email or "").strip()
    if not user_email or not had_active_key_before:
        return
    send_api_access_payment_confirmed(user_email)


def _handle_b2c_subscription_event(sub_obj: Any) -> None:
    """Sync a Stripe subscription object to user_subscriptions and API keys."""
    sub_d = _stripe_subscription_to_dict(sub_obj)
    sub_id = sub_d.get("id", "")
    metadata = dict(sub_d.get("metadata") or {})
    user_id = (metadata.get("user_id") or "").strip()
    user_email = (metadata.get("user_email") or "").strip()
    product_line = (metadata.get("product_line") or "").strip()
    tier = (metadata.get("tier") or "").strip()

    if not user_id or not product_line:
        logger.warning("_handle_b2c_subscription_event: missing metadata sub=%s", sub_id)
        return

    items = (sub_d.get("items") or {}).get("data") or []
    price_id = None
    if items and isinstance(items[0], dict):
        price_obj = items[0].get("price")
        if isinstance(price_obj, dict):
            price_id = price_obj.get("id")
        elif isinstance(price_obj, str):
            price_id = price_obj
    if price_id and price_id in _B2C_PRICE_TO_KEY:
        matched = _STRIPE_B2C_PRODUCTS[_B2C_PRICE_TO_KEY[price_id]]
        tier = matched["tier"]
        product_line = matched["product_line"]

    _STATUS_MAP = {
        "active": "active", "trialing": "active",
        "past_due": "past_due", "unpaid": "past_due",
        "incomplete": "past_due", "canceled": "cancelled",
    }
    status = _STATUS_MAP.get(sub_d.get("status", ""), "past_due")
    upsert_user_subscription(
        user_id=user_id,
        user_email=user_email,
        product_line=product_line,
        tier=tier,
        stripe_customer_id=sub_d.get("customer"),
        stripe_subscription_id=sub_id,
        stripe_price_id=price_id,
        status=status,
        current_period_end=sub_d.get("current_period_end"),
        cancel_at_period_end=bool(sub_d.get("cancel_at_period_end")),
    )

    if product_line == "api_access" and user_email:
        paid_active = status == "active"
        sync_api_key_quota_for_api_access(user_email, paid_active)
        if paid_active:
            _ensure_api_access_key_from_subscription(
                user_id=user_id,
                user_email=user_email,
                base_url=os.getenv("BASE_URL", "https://catalitium.com"),
            )


# ===================================================================
# Route handlers
# ===================================================================

@bp.get("/pricing")
def pricing():
    """B2C pricing page for Market Intelligence and API Access."""
    user = session.get("user")
    subs: Dict = {}
    if user:
        subs = get_user_subscriptions(user.get("id", ""))
    return render_template(
        "pricing.html",
        user=user,
        products=_STRIPE_B2C_PRODUCTS,
        subs=subs,
    )


@bp.post("/stripe/subscribe")
def stripe_subscribe():
    """Start a Stripe Checkout Session for a B2C subscription."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("stripe_routes.pricing"))

    plan_key = (request.form.get("plan_key") or "").strip()
    product = _STRIPE_B2C_PRODUCTS.get(plan_key)
    if not product or not product["price_id"]:
        flash("Invalid plan selected.", "error")
        return redirect(url_for("stripe_routes.pricing"))

    user_id = user.get("id", "")
    user_email = user.get("email", "")
    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))

    subs = get_user_subscriptions(user_id)
    existing = subs.get(product["product_line"])
    if existing and existing.get("status") == "active" and existing.get("stripe_subscription_id"):
        try:
            sub = _stripe.Subscription.retrieve(existing["stripe_subscription_id"])
            item_id = sub["items"]["data"][0]["id"]
            _stripe.Subscription.modify(
                existing["stripe_subscription_id"],
                items=[{"id": item_id, "price": product["price_id"]}],
                proration_behavior="create_prorations",
            )
            flash(f"Switched to {product['name']}. Changes apply immediately.", "success")
            return redirect(url_for("stripe_routes.subscription_manage"))
        except Exception as exc:
            logger.error("stripe_subscribe: plan change failed %s", exc)
            flash("Could not change plan. Please contact support.", "error")
            return redirect(url_for("stripe_routes.pricing"))

    try:
        checkout_session = _stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": product["price_id"], "quantity": 1}],
            customer_email=user_email,
            success_url=f"{base_url}/stripe/subscription/success?plan_key={plan_key}",
            cancel_url=f"{base_url}/pricing",
            metadata={
                "user_id": user_id,
                "user_email": user_email,
                "plan_key": plan_key,
                "product_line": product["product_line"],
                "tier": product["tier"],
                "checkout_type": "b2c_subscription",
            },
            subscription_data={
                "metadata": {
                    "user_id": user_id,
                    "user_email": user_email,
                    "plan_key": plan_key,
                    "product_line": product["product_line"],
                    "tier": product["tier"],
                }
            },
        )
        return redirect(checkout_session.url, 303)
    except Exception as exc:
        logger.error("stripe_subscribe: checkout creation failed %s", exc)
        flash("Could not start checkout. Please try again.", "error")
        return redirect(url_for("stripe_routes.pricing"))


@bp.get("/stripe/subscription/success")
def subscription_success():
    """Landing page after a successful B2C subscription checkout."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))
    plan_key = request.args.get("plan_key", "")
    product = _STRIPE_B2C_PRODUCTS.get(plan_key)
    if plan_key == "api_access":
        flash(
            "API Access is active. Check your email for your key, then open Studio (Account) "
            "to see setup steps and documentation.",
            "success",
        )
        return redirect(url_for("studio", api_welcome="1"))
    return render_template("subscription_success.html", user=user, product=product)


@bp.get("/account/subscription")
def subscription_manage():
    """Manage active B2C subscriptions."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))
    subs = get_user_subscriptions(user.get("id", ""))
    return render_template(
        "subscription_manage.html",
        user=user,
        subs=subs,
        products=_STRIPE_B2C_PRODUCTS,
    )


@bp.post("/account/subscription/cancel")
def subscription_cancel():
    """Cancel a B2C subscription at period end."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("stripe_routes.subscription_manage"))

    product_line = (request.form.get("product_line") or "").strip()
    subs = get_user_subscriptions(user.get("id", ""))
    sub = subs.get(product_line)
    if not sub or not sub.get("stripe_subscription_id"):
        flash("No active subscription found.", "error")
        return redirect(url_for("stripe_routes.subscription_manage"))

    try:
        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        _stripe.Subscription.modify(
            sub["stripe_subscription_id"],
            cancel_at_period_end=True,
        )
        flash("Subscription cancelled. You'll keep access until the end of the billing period.", "success")
    except Exception as exc:
        logger.error("subscription_cancel: failed %s", exc)
        flash("Could not cancel subscription. Please contact support.", "error")

    return redirect(url_for("stripe_routes.subscription_manage"))


# ------------------------------------------------------------------
# Stripe B2B job posting payments
# ------------------------------------------------------------------

@bp.get("/post-a-job")
def post_a_job():
    """B2B pricing page for companies to post jobs."""
    user = session.get("user")
    return render_template(
        "post_job_pricing.html",
        user=user,
        products=_STRIPE_PRODUCTS,
        stripe_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
    )


@bp.post("/stripe/checkout")
def stripe_checkout():
    """Create a Stripe Checkout Session and redirect the user."""
    user = session.get("user")
    if not user:
        flash("Please sign in to purchase a job posting.", "error")
        return redirect(url_for("register"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))
    if not _stripe:
        flash("Payment service unavailable. Please try again later.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    plan_key = (request.form.get("plan_key") or "").strip()
    product = _STRIPE_PRODUCTS.get(plan_key)
    if not product or not product["price_id"]:
        flash("Invalid plan selected.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))
    user_email = user.get("email", "")
    user_id = user.get("id", "")

    try:
        params: Dict[str, Any] = {
            "mode": product["mode"],
            "line_items": [{"price": product["price_id"], "quantity": 1}],
            "customer_email": user_email,
            "success_url": f"{base_url}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base_url}/stripe/cancel",
            "metadata": {
                "user_id": user_id,
                "user_email": user_email,
                "plan_key": plan_key,
                "plan_name": product["name"],
            },
        }
        if product["mode"] == "subscription":
            params["subscription_data"] = {"metadata": {"user_id": user_id, "plan_key": plan_key}}

        checkout_session = _stripe.checkout.Session.create(**params)
    except Exception as exc:
        logger.warning("stripe_checkout error: %s", exc)
        flash("Could not initiate payment. Please try again.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    insert_stripe_order(
        stripe_session_id=checkout_session.id,
        user_id=user_id,
        user_email=user_email,
        price_id=product["price_id"],
        plan_key=plan_key,
        plan_name=product["name"],
    )
    return redirect(checkout_session.url, 303)


@bp.get("/stripe/success")
def stripe_success():
    """Landing page after successful Stripe Checkout."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        flash("No payment session found.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    order = get_stripe_order(session_id)
    if not order or order.get("user_id") != user.get("id"):
        flash("Payment not found or does not belong to your account.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    product = _STRIPE_PRODUCTS.get(order.get("plan_key", ""))
    return render_template(
        "post_job_submit.html",
        user=user,
        order=order,
        product=product,
    )


@bp.post("/stripe/submit-job")
def stripe_submit_job():
    """Handle job details submission after a successful payment."""
    user = session.get("user")
    if not user:
        return redirect(url_for("register"))
    if not csrf_valid():
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    session_id = (request.form.get("stripe_session_id") or "").strip()
    order = get_stripe_order(session_id) if session_id else None
    if not order or order.get("user_id") != user.get("id"):
        flash("Invalid or unauthorised payment session.", "error")
        return redirect(url_for("stripe_routes.post_a_job"))

    if order.get("job_submitted_at"):
        flash("A job has already been submitted for this order.", "error")
        return redirect(url_for("hire"))

    job_title = (request.form.get("job_title") or "").strip()
    company = (request.form.get("company") or "").strip()
    location = (request.form.get("location") or "").strip()
    description = (request.form.get("description") or "").strip()
    salary_range = (request.form.get("salary_range") or "").strip()
    apply_url = (request.form.get("apply_url") or "").strip()

    if len(job_title) < 2:
        flash("Please enter a job title.", "error")
        return redirect(url_for("stripe_routes.stripe_success", session_id=session_id))
    if len(company) < 2:
        flash("Please enter a company name.", "error")
        return redirect(url_for("stripe_routes.stripe_success", session_id=session_id))
    if len(description) < 20:
        flash("Please add a job description (at least 20 characters).", "error")
        return redirect(url_for("stripe_routes.stripe_success", session_id=session_id))

    description_full = description
    if apply_url:
        description_full += f"\n\nApply here: {apply_url}"
    if location:
        description_full = f"Location: {location}\n\n{description_full}"

    status = insert_job_posting(
        contact_email=order["user_email"],
        job_title=job_title,
        company=company,
        description=description_full,
        salary_range=salary_range or None,
    )
    if status != "ok":
        flash("Could not save your job. Please contact support.", "error")
        return redirect(url_for("stripe_routes.stripe_success", session_id=session_id))

    mark_stripe_order_job_submitted(stripe_session_id=session_id)

    admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    if admin_email:
        send_job_posting_admin_notification(
            admin_email=admin_email,
            job_title=job_title,
            company=company,
            plan_name=order["plan_name"],
            user_email=order["user_email"],
            session_id=session_id,
            location=location,
            salary_range=salary_range,
            apply_url=apply_url,
            description=description,
        )
    send_job_posting_confirmation(
        user_email=order["user_email"],
        job_title=job_title,
        company=company,
        plan_name=order["plan_name"],
    )

    flash("Job submitted! It will go live within 24 hours. Check your email for confirmation.", "success")
    return redirect(url_for("hire"))


@bp.get("/stripe/cancel")
def stripe_cancel():
    """Landing page when a user cancels Stripe Checkout."""
    user = session.get("user")
    return render_template("stripe_cancel.html", user=user)


@bp.post("/stripe/webhook")
def stripe_webhook():
    """Handle incoming Stripe webhook events."""
    if not _stripe:
        return jsonify({"error": "stripe_unavailable"}), 503

    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except _stripe.error.SignatureVerificationError:
        logger.warning("stripe_webhook: invalid signature")
        return jsonify({"error": "invalid_signature"}), 400
    except Exception as exc:
        logger.warning("stripe_webhook parse error: %s", exc)
        return jsonify({"error": "bad_payload"}), 400

    event_type = event.get("type", "")
    data_obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        cs_id = data_obj.get("id", "")
        customer_id = data_obj.get("customer") or None
        subscription_id = data_obj.get("subscription") or None
        mark_stripe_order_paid(
            stripe_session_id=cs_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        logger.info("stripe_webhook: order paid session=%s", cs_id)

        if subscription_id and data_obj.get("mode") == "subscription":
            try:
                _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
                sub_raw = _stripe.Subscription.retrieve(subscription_id)
                sub_d = _stripe_subscription_to_dict(sub_raw)
                sess_meta = data_obj.get("metadata") or {}
                sub_meta = dict(sub_d.get("metadata") or {})
                merged_meta = {**sub_meta}
                for k, v in sess_meta.items():
                    if v is not None and str(v).strip() != "":
                        merged_meta.setdefault(k, str(v).strip())
                sub_d["metadata"] = merged_meta
                uemail = (sess_meta.get("user_email") or merged_meta.get("user_email") or "").strip()
                uid = (sess_meta.get("user_id") or merged_meta.get("user_id") or "").strip()
                plan_key = (sess_meta.get("plan_key") or "").strip()
                prior = get_api_key_by_email(uemail) if uemail else None
                had_active = bool(prior and prior.get("is_active"))
                was_pending = bool(prior and not prior.get("is_active"))
                _handle_b2c_subscription_event(sub_d)
                if plan_key == "api_access" and uemail:
                    base = os.getenv("BASE_URL", "https://catalitium.com").rstrip("/")
                    after = get_api_key_by_email(uemail)
                    if was_pending and after and not after.get("is_active"):
                        tok = after.get("confirm_token")
                        if tok:
                            send_api_key_activation_reminder(uemail, f"{base}/api/keys/confirm?token={tok}")
                    _checkout_api_access_confirmation_email(uemail, had_active)
            except Exception as exc:
                logger.warning("stripe_webhook: checkout subscription sync failed %s", exc)

    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _handle_b2c_subscription_event(data_obj)
        logger.info("stripe_webhook: subscription synced sub=%s type=%s", data_obj.get("id"), event_type)

    elif event_type == "customer.subscription.deleted":
        sub_id = data_obj.get("id", "")
        existing = get_subscription_by_stripe_id(sub_id)
        if existing:
            upsert_user_subscription(
                user_id=existing["user_id"],
                user_email=existing["user_email"],
                product_line=existing["product_line"],
                tier=existing["tier"],
                stripe_subscription_id=sub_id,
                status="cancelled",
            )
            if existing.get("product_line") == "api_access" and existing.get("user_email"):
                sync_api_key_quota_for_api_access(existing["user_email"], False)
        logger.info("stripe_webhook: subscription cancelled sub=%s", sub_id)

    elif event_type == "invoice.payment_succeeded":
        sub_id = data_obj.get("subscription")
        if sub_id:
            try:
                _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
                sub_obj = _stripe.Subscription.retrieve(sub_id)
                _handle_b2c_subscription_event(sub_obj)
            except Exception as exc:
                logger.warning("stripe_webhook: invoice.payment_succeeded retrieve failed %s", exc)

    elif event_type == "invoice.payment_failed":
        sub_id = data_obj.get("subscription")
        customer_id = data_obj.get("customer", "")
        if sub_id:
            existing = get_subscription_by_stripe_id(sub_id)
            if existing:
                upsert_user_subscription(
                    user_id=existing["user_id"],
                    user_email=existing["user_email"],
                    product_line=existing["product_line"],
                    tier=existing["tier"],
                    stripe_subscription_id=sub_id,
                    status="past_due",
                )
                if existing.get("product_line") == "api_access" and existing.get("user_email"):
                    sync_api_key_quota_for_api_access(existing["user_email"], False)
        logger.warning("stripe_webhook: payment failed customer=%s sub=%s", customer_id, sub_id)

    return jsonify({"status": "ok"}), 200
