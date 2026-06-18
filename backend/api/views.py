import random
import re
import os
import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib.auth import logout
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Bill,
    BillItem,
    BusinessProfile,
    BusinessSubscription,
    Category,
    CreditCustomer,
    CreditPayment,
    Customer,
    LoginOTP,
    Product,
    SubscriptionPlan,
    SubscriptionPaymentOrder,
    UserProfile,
)
from .serializers import (
    BillSerializer,
    BusinessSubscriptionSerializer,
    BusinessProfileSerializer,
    CategorySerializer,
    CreditCustomerSerializer,
    CreditPaymentSerializer,
    CustomerSerializer,
    FirebaseLoginSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    ProductSerializer,
    RegisterSerializer,
    SubscriptionPlanSerializer,
)

logger = logging.getLogger(__name__)


def get_local_day_range(day):
    start = timezone.make_aware(
        datetime.combine(day, time.min),
        timezone.get_current_timezone(),
    )
    return start, start + timedelta(days=1)


REPORT_PERIODS = {"daily", "weekly", "monthly"}


def get_report_period_range(period):
    today = timezone.localdate()

    if period == "weekly":
        start_day = today - timedelta(days=today.weekday())
        label = "Weekly"
    elif period == "monthly":
        start_day = today.replace(day=1)
        label = "Monthly"
    else:
        start_day = today
        label = "Daily"

    start_at, _ = get_local_day_range(start_day)
    _, end_at = get_local_day_range(today)
    return start_day, today, start_at, end_at, label


def normalize_report_period(request):
    period = request.query_params.get("period", "monthly").lower()
    return period if period in REPORT_PERIODS else "monthly"


def money(value):
    amount = value if value is not None else Decimal("0")
    return f"Rs. {Decimal(amount):.2f}"


def pdf_escape(value):
    return re.sub(r"([\\()])", r"\\\1", str(value))


def build_simple_pdf(lines):
    content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]

    for index, line in enumerate(lines):
        if index:
            content_lines.append("T*")
        content_lines.append(f"({pdf_escape(line)}) Tj")

    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii",
        ),
    )
    return bytes(pdf)


def build_pdf_document(page_contents, page_width=842, page_height=595):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    page_ids = []

    for content in page_contents:
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode("ascii"),
        )
        content_bytes = content.encode("latin-1", "replace")
        objects.append(
            b"<< /Length "
            + str(len(content_bytes)).encode("ascii")
            + b" >>\nstream\n"
            + content_bytes
            + b"\nendstream",
        )

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii",
        ),
    )
    return bytes(pdf)


def pdf_text(x, y, text, size=9, bold=False):
    font = "F2" if bold else "F1"
    return f"0 g BT /{font} {size} Tf {x:.2f} {y:.2f} Td ({pdf_escape(text)}) Tj ET"


def pdf_line(x1, y1, x2, y2, width=0.6):
    return f"0 G {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"


def pdf_rect_fill(x, y, width, height, color=(1.0, 0.82, 0.36)):
    red, green, blue = color
    return f"{red:.2f} {green:.2f} {blue:.2f} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f"


def truncate_pdf_cell(value, width, font_size=8):
    text = str(value or "")
    max_chars = max(3, int((width - 8) / (font_size * 0.52)))

    if len(text) <= max_chars:
        return text

    return f"{text[:max_chars - 3]}..."


def build_report_table_pdf(title, period_line, generated_line, tables, totals):
    page_width = 842
    page_height = 595
    left = 34
    top = 560
    bottom = 42
    row_height = 22
    page_contents = []
    commands = []
    y = top

    def start_page():
        nonlocal commands, y
        if commands:
            page_contents.append("\n".join(commands))
        commands = [
            pdf_text(left, 564, title, size=15, bold=True),
            pdf_text(left, 545, period_line, size=9),
            pdf_text(left, 531, generated_line, size=9),
        ]
        y = 506

    def ensure_space(required_height):
        if y - required_height < bottom:
            start_page()

    def draw_table(section_title, columns, rows, min_rows=4):
        nonlocal y
        row_count = max(len(rows), min_rows)
        total_width = sum(width for _, width, *_ in columns)
        remaining_rows = row_count
        row_index = 0
        actual_rows = list(rows) + [None] * (row_count - len(rows))

        while remaining_rows > 0:
            ensure_space(58)
            max_rows_on_page = max(1, int((y - bottom - row_height) / row_height))
            rows_this_page = min(remaining_rows, max_rows_on_page)
            table_top = y - 20
            table_bottom = table_top - row_height * (rows_this_page + 1)

            commands.append(pdf_text(left, y, section_title, size=11, bold=True))
            commands.append(pdf_rect_fill(left, table_top - row_height, total_width, row_height))

            x = left
            commands.append(pdf_line(left, table_top, left + total_width, table_top))
            for _, width, *_ in columns:
                commands.append(pdf_line(x, table_top, x, table_bottom))
                x += width
            commands.append(pdf_line(left + total_width, table_top, left + total_width, table_bottom))

            for line_index in range(rows_this_page + 2):
                line_y = table_top - (line_index * row_height)
                commands.append(pdf_line(left, line_y, left + total_width, line_y))

            x = left
            for label, width, *_ in columns:
                commands.append(
                    pdf_text(
                        x + 5,
                        table_top - 14,
                        truncate_pdf_cell(label, width, 8),
                        size=8,
                        bold=True,
                    ),
                )
                x += width

            for local_index in range(rows_this_page):
                row = actual_rows[row_index + local_index]
                text_y = table_top - row_height * (local_index + 1) - 14
                x = left

                for column in columns:
                    _, width, key, *options = column
                    align_right = bool(options and options[0] == "right")
                    value = "" if row is None else row.get(key, "")
                    cell_text = truncate_pdf_cell(value, width, 8)
                    text_x = x + 5

                    if align_right:
                        text_x = x + width - 5 - min(width - 10, len(cell_text) * 4.2)

                    commands.append(pdf_text(text_x, text_y, cell_text, size=8))
                    x += width

            y = table_bottom - 24
            row_index += rows_this_page
            remaining_rows -= rows_this_page

            if remaining_rows > 0:
                start_page()

    start_page()

    for table in tables:
        draw_table(
            table["title"],
            table["columns"],
            table["rows"],
            table.get("min_rows", 4),
        )

    ensure_space(120)
    total_columns = (
        ("Description", 260, "label"),
        ("Amount", 140, "value", "right"),
    )
    draw_table(
        "Totals",
        total_columns,
        [{"label": label, "value": value} for label, value in totals],
        min_rows=len(totals),
    )

    if commands:
        page_contents.append("\n".join(commands))

    return build_pdf_document(page_contents, page_width=page_width, page_height=page_height)


def build_receipt_pdf(lines):
    page_width = 226
    line_height = 12
    top_padding = 18
    bottom_padding = 18
    page_height = max(360, top_padding + bottom_padding + (len(lines) * line_height))
    start_y = page_height - top_padding
    content_lines = ["BT", "/F1 9 Tf", f"12 {start_y} Td", f"{line_height} TL"]

    for index, line in enumerate(lines):
      if index:
          content_lines.append("T*")
      content_lines.append(f"({pdf_escape(line)}) Tj")

    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii",
        ),
    )
    return bytes(pdf)


def receipt_center(value, width=32):
    return str(value)[:width].center(width)


def receipt_pair(left, right, width=32):
    left = str(left)
    right = str(right)
    available = max(1, width - len(right))
    return f"{left[:available].ljust(available)}{right}"[:width]


def report_cell(value, width):
    return str(value or "")[:width].ljust(width)


def report_money(value):
    return f"{Decimal(value or 0):.2f}"


def report_bill_items(bill):
    items = [str(item.name) for item in bill.items.all()]
    return ", ".join(items) if items else "-"


def report_table_row(values, widths):
    return " ".join(
        report_cell(value, width)
        for value, width in zip(values, widths)
    )


def build_bill_pdf_lines(bill):
    business = bill.business
    created_at = timezone.localtime(bill.created_at)
    lines = [
        receipt_center(business.name),
        receipt_center(business.address) if business.address else "",
        receipt_center(f"Phone: {business.phone}") if business.phone else "",
        receipt_center(f"GSTIN: {business.gstin}") if business.gstin else "",
        "-" * 32,
        f"Invoice: {bill.invoice_id}",
        f"Date: {created_at:%d %b %Y, %I:%M %p}",
        f"Payment: {bill.payment_mode}",
        "-" * 32,
    ]

    if bill.customer:
        lines.extend(
            [
                f"Customer: {bill.customer.full_name}",
                f"Customer phone: {bill.customer.phone}" if bill.customer.phone else "",
            ],
        )

    if bill.payment_mode == "Credit" and bill.credit_customer:
        lines.extend(
            [
                f"Credit: {bill.credit_customer.name}",
                f"Phone: {bill.credit_customer.phone}" if bill.credit_customer.phone else "",
            ],
        )

    for item in bill.items.all():
        line_total = Decimal(item.price) * Decimal(item.quantity)
        lines.append(str(item.name)[:32])
        lines.append(
            receipt_pair(
                f"{item.quantity} x {money(item.price)}",
                money(line_total),
            ),
        )

    if not bill.items.exists():
        lines.append("No items in this bill.")

    lines.extend(
        [
            "-" * 32,
            receipt_pair("Subtotal", money(bill.subtotal)),
            receipt_pair("Discount", money(bill.discount)),
            receipt_pair("Tax", money(bill.tax)),
            receipt_pair("TOTAL", money(bill.grand_total)),
            receipt_pair("Paid", money(bill.paid_amount)) if bill.payment_mode == "Credit" else "",
            receipt_pair("Previous", money(bill.previous_balance)) if bill.payment_mode == "Credit" else "",
            receipt_pair("Remaining", money(bill.remaining_amount)) if bill.payment_mode == "Credit" else "",
            receipt_pair("Balance", money(bill.total_balance)) if bill.payment_mode == "Credit" else "",
            "-" * 32,
            receipt_center("Thank you"),
        ],
    )
    return [line for line in lines if line != ""]


def build_credit_payment_pdf_lines(payment):
    business = payment.business
    created_at = timezone.localtime(payment.created_at)
    lines = [
        receipt_center(business.name),
        receipt_center(business.address) if business.address else "",
        receipt_center(f"Phone: {business.phone}") if business.phone else "",
        receipt_center(f"GSTIN: {business.gstin}") if business.gstin else "",
        "-" * 32,
        f"Receipt: {payment.receipt_id or f'PAY-{payment.id:04d}'}",
        f"Date: {created_at:%d %b %Y, %I:%M %p}",
        f"Payment: {payment.payment_mode}",
        "-" * 32,
        f"Customer: {payment.customer.name}",
        f"Phone: {payment.customer.phone}" if payment.customer.phone else "",
        "-" * 32,
        receipt_pair("Previous", money(payment.previous_balance)),
        receipt_pair("Paid", money(payment.amount)),
        receipt_pair("Remaining", money(payment.remaining_balance)),
        "-" * 32,
        receipt_center("Payment received"),
    ]
    return [line for line in lines if line != ""]


def serialize_business_profile(profile, user=None, phone=""):
    if not profile:
        return None

    return {
        "id": profile.id,
        "name": profile.name,
        "businessType": profile.business_type,
        "ownerName": user.get_full_name() or user.username if user else "",
        "phone": profile.phone or phone,
        "address": profile.address,
        "city": "",
        "state": "",
        "gstin": profile.gstin,
    }


def get_request_business(request):
    try:
        return request.user.profile.business_profile
    except (AttributeError, UserProfile.DoesNotExist):
        return None


def require_request_business(request):
    business = get_request_business(request)
    if not business:
        raise PermissionDenied("Your login is not linked to a business.")
    return business


def require_kirana_business(request):
    business = require_request_business(request)
    if business.business_type != "Kirana shop":
        raise PermissionDenied("This feature is available only for Kirana shop businesses.")
    return business


def get_pdf_request_business(request):
    business = get_request_business(request)
    if business:
        return business

    access_token = request.query_params.get("access_token")
    if not access_token:
        return None

    try:
        validated_token = JWTAuthentication().get_validated_token(access_token)
        user = JWTAuthentication().get_user(validated_token)
    except Exception:
        return None

    class TokenRequest:
        pass

    token_request = TokenRequest()
    token_request.user = user
    return get_request_business(token_request)


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


APP_SUBSCRIPTION_PLANS = {
    "free_trial_7_days": {
        "name": "Free Trial",
        "code": "free_trial_7_days",
        "price": Decimal("0.00"),
        "billing_cycle": "monthly",
        "max_users": 1,
        "max_products": 50,
        "description": "7 days free trial for billing, products, customers, and reports.",
        "duration_days": 7,
        "status": "trial",
        "trial": True,
    },
    "monthly_499": {
        "name": "1 Month Plan",
        "code": "monthly_499",
        "price": Decimal("299.00"),
        "billing_cycle": "monthly",
        "max_users": 3,
        "max_products": 1000,
        "description": "1 month POS subscription for billing, products, customers, and reports.",
        "duration_days": 30,
        "status": "active",
        "trial": False,
    },
    "yearly_4999_machine": {
        "name": "1 Year Plan",
        "code": "yearly_4999_machine",
        "price": Decimal("4999.00"),
        "billing_cycle": "yearly",
        "max_users": 10,
        "max_products": 5000,
        "description": "1 year POS subscription with billing machine included.",
        "duration_days": 365,
        "status": "active",
        "trial": False,
    },
}


def get_app_subscription_plan(plan_code):
    plan_data = APP_SUBSCRIPTION_PLANS.get(plan_code)
    if not plan_data:
        return None, None

    plan, _ = SubscriptionPlan.objects.update_or_create(
        code=plan_data["code"],
        defaults={
            "name": plan_data["name"],
            "price": plan_data["price"],
            "billing_cycle": plan_data["billing_cycle"],
            "max_users": plan_data["max_users"],
            "max_products": plan_data["max_products"],
            "description": plan_data["description"],
            "is_active": True,
        },
    )
    return plan, plan_data


def get_or_create_subscription_business(data):
    business_id = data.get("business")
    phone = str(data.get("phone", "")).strip()
    business_name = str(data.get("business_name", "")).strip() or "BizPOS"

    if business_id:
        return get_object_or_404(BusinessProfile, id=business_id)

    if phone:
        business, created = BusinessProfile.objects.get_or_create(
            phone=phone,
            defaults={
                "name": business_name,
                "business_type": data.get("business_type", "Others"),
                "email": data.get("email", ""),
                "address": data.get("address", ""),
                "gstin": data.get("gstin", ""),
            },
        )
        update_fields = []
        if not created and business.name != business_name:
            business.name = business_name
            update_fields.append("name")
        if not created and data.get("address") and business.address != data.get("address"):
            business.address = data.get("address", "")
            update_fields.append("address")
        if update_fields:
            update_fields.append("updated_at")
            business.save(update_fields=update_fields)
        return business

    return BusinessProfile.objects.create(
        name=business_name,
        business_type=data.get("business_type", "Others"),
        email=data.get("email", ""),
        address=data.get("address", ""),
        gstin=data.get("gstin", ""),
    )


def activate_business_subscription(business, plan, plan_data, seats=1, notes=""):
    today = timezone.localdate()
    ends_at = today + timedelta(days=plan_data["duration_days"])

    subscription, _ = BusinessSubscription.objects.update_or_create(
        business=business,
        defaults={
            "plan": plan,
            "status": plan_data["status"],
            "starts_at": today,
            "ends_at": ends_at,
            "trial_ends_at": ends_at if plan_data["trial"] else None,
            "seats": seats or 1,
            "notes": notes or f"Created from mobile app subscription screen. Plan: {plan.name}.",
        },
    )
    return subscription


def get_paid_app_plan(plan_code):
    plan, plan_data = get_app_subscription_plan(plan_code)
    if not plan or plan_data["trial"] or plan.price <= 0:
        return None, None
    return plan, plan_data


def create_razorpay_order(amount, currency, receipt, notes):
    missing_settings = [
        name
        for name, value in (
            ("RAZORPAY_KEY_ID", settings.RAZORPAY_KEY_ID),
            ("RAZORPAY_KEY_SECRET", settings.RAZORPAY_KEY_SECRET),
        )
        if not value
    ]
    if missing_settings:
        raise RuntimeError(
            f"Missing backend env value(s): {', '.join(missing_settings)}.",
        )

    payload = json.dumps(
        {
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        },
    ).encode("utf-8")
    credentials = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode("utf-8")
    auth_header = base64.b64encode(credentials).decode("ascii")
    request = urllib.request.Request(
        "https://api.razorpay.com/v1/orders",
        data=payload,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def verify_razorpay_signature(order_id, payment_id, signature):
    message = f"{order_id}|{payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def normalize_phone_digits(value):
    return re.sub(r"\D", "", str(value or ""))


def normalize_local_phone_digits(value):
    digits = normalize_phone_digits(value)

    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]

    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]

    return digits


def mask_phone_for_logs(value):
    digits = normalize_local_phone_digits(value)
    if len(digits) <= 4:
        return "****" if digits else ""
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def sanitize_register_payload_for_logs(data):
    if not hasattr(data, "items"):
        return {}

    sanitized = {}
    for key, value in data.items():
        if key == "password":
            continue
        if key == "phone":
            sanitized[key] = mask_phone_for_logs(value)
            continue
        sanitized[key] = value

    return sanitized


def get_phone_lookup_candidates(phone):
    digits = normalize_phone_digits(phone)
    local_digits = normalize_local_phone_digits(phone)
    candidates = {str(phone or "").strip(), digits, f"+{digits}"}

    if local_digits:
        candidates.update(
            {
                local_digits,
                f"0{local_digits}",
                f"91{local_digits}",
                f"+91{local_digits}",
            },
        )

    if len(digits) == 12 and digits.startswith("91"):
        candidates.add(digits[2:])
    if len(digits) == 10:
        candidates.add(f"91{digits}")
        candidates.add(f"+91{digits}")
    return {candidate for candidate in candidates if candidate}


def get_user_profile_by_phone(phone):
    candidates = get_phone_lookup_candidates(phone)

    profile = (
        UserProfile.objects.select_related("user", "business_profile")
        .filter(phone__in=candidates)
        .first()
    )
    if profile:
        return profile

    local_digits = normalize_local_phone_digits(phone)
    if not local_digits:
        return None

    for profile in UserProfile.objects.select_related("user", "business_profile").all():
        if normalize_local_phone_digits(profile.phone) == local_digits:
            return profile

    return None


def requested_phone_matches_verified_phone(requested_phone, verified_phone):
    if not requested_phone:
        return True

    requested_digits = normalize_local_phone_digits(requested_phone)
    verified_digits = normalize_local_phone_digits(verified_phone)
    return bool(
        requested_digits
        and verified_digits
        and requested_digits == verified_digits
    )


def get_firebase_app():
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as caught_error:
        raise RuntimeError("Install backend dependency firebase-admin.") from caught_error

    if firebase_admin._apps:
        return firebase_admin.get_app()

    credential_path = settings.FIREBASE_SERVICE_ACCOUNT_PATH
    options = {}
    if settings.FIREBASE_PROJECT_ID:
        options["projectId"] = settings.FIREBASE_PROJECT_ID

    if credential_path:
        if not os.path.isabs(credential_path):
            credential_path = os.path.join(settings.BASE_DIR, credential_path)
        if not os.path.exists(credential_path):
            raise RuntimeError(f"Firebase service account file not found: {credential_path}")

        with open(credential_path, encoding="utf-8") as credential_file:
            credential_data = json.load(credential_file)

        credential_project_id = credential_data.get("project_id", "")
        if (
            settings.FIREBASE_CLIENT_PROJECT_ID
            and settings.FIREBASE_PROJECT_ID != settings.FIREBASE_CLIENT_PROJECT_ID
        ):
            raise RuntimeError(
                "Firebase Admin project does not match the mobile Firebase project."
            )

        if (
            credential_project_id
            and settings.FIREBASE_PROJECT_ID
            and credential_project_id != settings.FIREBASE_PROJECT_ID
        ):
            logger.warning(
                "Firebase service account project %s differs from token verification project %s.",
                credential_project_id,
                settings.FIREBASE_PROJECT_ID,
            )

        return firebase_admin.initialize_app(credentials.Certificate(credential_path), options)

    return firebase_admin.initialize_app(options=options or None)


def verify_firebase_id_token(id_token):
    try:
        from firebase_admin import auth as firebase_auth
    except ImportError as caught_error:
        raise RuntimeError("Install backend dependency firebase-admin.") from caught_error

    get_firebase_app()
    return firebase_auth.verify_id_token(id_token)


def owner_session_required(view_func):
    def wrapped(request, *args, **kwargs):
        if request.session.get("subscription_owner_logged_in"):
            return view_func(request, *args, **kwargs)
        return redirect("/subscription-admin/login/")

    return wrapped


@require_http_methods(["GET", "POST"])
def subscription_owner_login(request):
    error = ""

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        owner_username = os.environ.get("SUBSCRIPTION_OWNER_USERNAME", "owner")
        owner_password = os.environ.get("SUBSCRIPTION_OWNER_PASSWORD", "Owner@12345")

        if username == owner_username and password == owner_password:
            request.session["subscription_owner_logged_in"] = True
            return redirect("subscription-admin-root")

        error = "Invalid owner username or password."

    return render(
        request,
        "api/subscription_login.html",
        {
            "error": error,
            "default_username": os.environ.get("SUBSCRIPTION_OWNER_USERNAME", "owner"),
        },
    )


class RegisterView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "Registration validation failed. host=%s origin=%s errors=%s payload=%s",
                request.get_host(),
                request.headers.get("Origin", ""),
                serializer.errors,
                sanitize_register_payload_for_logs(request.data),
            )
            return Response(
                {
                    **serializer.errors,
                    "detail": "Registration request is invalid.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        selected_plan_code = serializer.validated_data.get("plan_code") or "free_trial_7_days"

        with transaction.atomic():
            selected_plan, selected_plan_data = get_app_subscription_plan(selected_plan_code)

            if not selected_plan:
                logger.warning(
                    "Registration rejected invalid subscription plan. host=%s plan_code=%s payload=%s",
                    request.get_host(),
                    selected_plan_code,
                    sanitize_register_payload_for_logs(request.data),
                )
                return Response(
                    {"detail": "Invalid subscription plan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = serializer.save()
            subscription = None

            if user.profile.business_profile and selected_plan_data["trial"]:
                subscription = activate_business_subscription(
                    user.profile.business_profile,
                    selected_plan,
                    selected_plan_data,
                    notes="Automatically created when the business registered.",
                )

        refresh = RefreshToken.for_user(user)
        business_profile = serialize_business_profile(
            user.profile.business_profile,
            user=user,
            phone=user.profile.phone,
        )

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "phone": user.profile.phone,
                },
                "business_profile": business_profile,
                "subscription": (
                    BusinessSubscriptionSerializer(subscription).data
                    if subscription
                    else None
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class OTPRequestView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        normalized_phone = normalize_local_phone_digits(phone)

        profile = get_user_profile_by_phone(normalized_phone)
        if profile is None:
            return Response(
                {"detail": "This phone number is not registered."},
                status=status.HTTP_404_NOT_FOUND,
            )

        code = f"{random.randint(100000, 999999)}"
        otp = LoginOTP.objects.create(
            user=profile.user,
            phone=profile.phone,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response_data = {
            "detail": "OTP sent successfully.",
            "expires_at": otp.expires_at,
        }

        if request.query_params.get("debug") == "true":
            response_data["otp"] = code

        return Response(response_data, status=status.HTTP_201_CREATED)


class OTPVerifyView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        profile = get_user_profile_by_phone(phone)
        lookup_phone = profile.phone if profile else normalize_local_phone_digits(phone)
        code = serializer.validated_data["otp"]

        try:
            otp = LoginOTP.objects.select_related("user").filter(
                phone=lookup_phone,
                purpose="login",
            ).latest("created_at")
        except LoginOTP.DoesNotExist:
            return Response(
                {"detail": "OTP not found. Please request a new OTP."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if otp.is_verified:
            return Response(
                {"detail": "OTP already used. Please request a new OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.is_expired:
            return Response(
                {"detail": "OTP expired. Please request a new OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.attempts >= 5:
            return Response(
                {"detail": "Too many attempts. Please request a new OTP."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp.attempts += 1

        if otp.code != code:
            otp.save(update_fields=("attempts", "updated_at"))
            return Response(
                {"detail": "Invalid OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp.verified_at = timezone.now()
        otp.save(update_fields=("attempts", "verified_at", "updated_at"))

        refresh = RefreshToken.for_user(otp.user)
        business_profile = None

        try:
            profile = otp.user.profile
            business_profile = serialize_business_profile(
                profile.business_profile,
                user=otp.user,
                phone=phone,
            )
        except UserProfile.DoesNotExist:
            business_profile = None

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": otp.user.id,
                    "username": otp.user.username,
                    "email": otp.user.email,
                    "phone": phone,
                },
                "business_profile": business_profile,
            },
        )


class FirebaseLoginView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = FirebaseLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            decoded_token = verify_firebase_id_token(serializer.validated_data["id_token"])
        except RuntimeError as caught_error:
            logger.exception("Firebase Admin configuration error during login.")
            return Response({"detail": str(caught_error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as caught_error:
            logger.exception(
                "Firebase ID token verification failed: %s",
                caught_error.__class__.__name__,
            )
            return Response(
                {
                    "detail": "Firebase login token could not be verified.",
                    "code": "firebase_token_verification_failed",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        firebase_phone = decoded_token.get("phone_number", "")
        requested_phone = serializer.validated_data.get("phone", "")

        if not firebase_phone:
            logger.warning("Verified Firebase token does not contain a phone number.")
            return Response(
                {
                    "detail": "Firebase token does not include a verified phone number.",
                    "code": "firebase_phone_missing",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not requested_phone_matches_verified_phone(requested_phone, firebase_phone):
            logger.warning("Requested phone does not match the verified Firebase phone.")
            return Response(
                {
                    "detail": "Verified Firebase phone does not match requested phone.",
                    "code": "firebase_phone_mismatch",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = get_user_profile_by_phone(firebase_phone) or get_user_profile_by_phone(requested_phone)

        if profile is None:
            return Response(
                {"detail": "This phone number is not registered."},
                status=status.HTTP_404_NOT_FOUND,
            )

        refresh = RefreshToken.for_user(profile.user)
        business_profile = serialize_business_profile(
            profile.business_profile,
            user=profile.user,
            phone=profile.phone,
        )

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": profile.user.id,
                    "username": profile.user.username,
                    "email": profile.user.email,
                    "phone": profile.phone,
                },
                "business_profile": business_profile,
            },
        )


class BusinessProfileViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessProfileSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business:
            return BusinessProfile.objects.none()
        return BusinessProfile.objects.filter(id=business.id)


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    search_fields = ("name", "code", "description")

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business:
            return Category.objects.none()
        return Category.objects.filter(business=business)

    def perform_create(self, serializer):
        serializer.save(business=require_request_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_request_business(self.request))


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    search_fields = ("name", "barcode", "description", "category__name")

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business:
            return Product.objects.none()
        return Product.objects.select_related("category").filter(business=business)

    def perform_create(self, serializer):
        serializer.save(business=require_request_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_request_business(self.request))


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = (permissions.IsAuthenticated,)
    search_fields = ("full_name", "phone", "email", "city", "gstin")

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business:
            return Customer.objects.none()
        return Customer.objects.filter(business=business)

    def perform_create(self, serializer):
        serializer.save(business=require_request_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_request_business(self.request))


class CreditCustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CreditCustomerSerializer
    permission_classes = (permissions.IsAuthenticated,)
    search_fields = ("name", "phone")

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business or business.business_type != "Kirana shop":
            return CreditCustomer.objects.none()

        queryset = CreditCustomer.objects.filter(business=business)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(phone__icontains=search),
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(business=require_kirana_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_kirana_business(self.request))

    @action(detail=True, methods=["get"], url_path="ledger")
    def ledger(self, request, pk=None):
        business = require_kirana_business(request)
        customer = self.get_object()
        bills = (
            Bill.objects.prefetch_related("items")
            .filter(
                business=business,
                credit_customer=customer,
                payment_mode="Credit",
            )
        )
        payments = CreditPayment.objects.select_related("bill").filter(
            business=business,
            customer=customer,
        )
        ordered_records = [
            ("bill", bill.created_at, bill)
            for bill in bills
        ] + [
            ("payment", payment.created_at, payment)
            for payment in payments
        ]
        ordered_records.sort(key=lambda record: record[1])
        records = []
        running_balance = None

        for record_type, _, source in ordered_records:
            if record_type == "bill":
                bill = source
                previous_balance = Decimal(bill.previous_balance or 0)
                balance_after = Decimal(bill.total_balance or 0)
                balance_change = Decimal(bill.remaining_amount or 0)
                running_balance = balance_after
                records.append(
                    {
                        "type": "bill",
                        "id": bill.id,
                        "created_at": bill.created_at,
                        "title": f"Bill {bill.invoice_id}",
                        "invoiceId": bill.invoice_id,
                        "amount": bill.grand_total,
                        "paidAmount": bill.paid_amount,
                        "paymentMode": bill.payment_mode,
                        "balanceChange": balance_change,
                        "previousBalance": previous_balance,
                        "balanceAfter": balance_after,
                        "itemsCount": len(bill.items.all()),
                    },
                )
                continue

            payment = source
            stored_previous_balance = Decimal(payment.previous_balance or 0)
            stored_remaining_balance = Decimal(payment.remaining_balance or 0)

            if stored_previous_balance or stored_remaining_balance:
                previous_balance = stored_previous_balance
                balance_after = stored_remaining_balance
            elif running_balance is not None:
                previous_balance = running_balance
                balance_after = max(
                    Decimal("0.00"),
                    previous_balance - Decimal(payment.amount or 0),
                )
            else:
                previous_balance = stored_previous_balance
                balance_after = stored_remaining_balance

            running_balance = balance_after
            records.append(
                {
                    "type": "payment",
                    "id": payment.id,
                    "created_at": payment.created_at,
                    "title": f"Payment {payment.receipt_id or f'PAY-{payment.id:04d}'}",
                    "receiptId": payment.receipt_id or f"PAY-{payment.id:04d}",
                    "amount": payment.amount,
                    "paymentMode": payment.payment_mode,
                    "balanceChange": -Decimal(payment.amount),
                    "previousBalance": previous_balance,
                    "balanceAfter": balance_after,
                    "note": payment.note,
                },
            )

        records.sort(key=lambda record: record["created_at"], reverse=True)
        return Response(
            {
                "customer": CreditCustomerSerializer(customer).data,
                "currentBalance": customer.current_balance,
                "results": records,
            },
        )


class CreditPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = CreditPaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business or business.business_type != "Kirana shop":
            return CreditPayment.objects.none()

        queryset = CreditPayment.objects.select_related("customer", "bill").filter(
            business=business,
        )
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(business=require_kirana_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_kirana_business(self.request))

    def perform_destroy(self, instance):
        business = require_kirana_business(self.request)
        if instance.business_id != business.id:
            raise PermissionDenied("Select a payment from your business.")

        customer = instance.customer
        self.get_serializer().reverse_payment_allocations(instance)
        customer.current_balance = Decimal(customer.current_balance or 0) + Decimal(instance.amount or 0)
        customer.save(update_fields=("current_balance", "updated_at"))
        instance.delete()


class BillViewSet(viewsets.ModelViewSet):
    serializer_class = BillSerializer
    permission_classes = (permissions.IsAuthenticated,)
    search_fields = ("invoice_id", "customer__full_name", "customer__phone")

    def get_queryset(self):
        business = get_request_business(self.request)
        if not business:
            return Bill.objects.none()
        queryset = Bill.objects.prefetch_related("items").select_related(
            "customer",
            "credit_customer",
        ).filter(
            business=business,
        )
        payment_mode = self.request.query_params.get("payment_mode", "").strip()
        if payment_mode:
            queryset = queryset.filter(payment_mode=payment_mode)
        return queryset

    def perform_create(self, serializer):
        serializer.save(business=require_request_business(self.request))

    def perform_update(self, serializer):
        serializer.save(business=require_request_business(self.request))

    @action(detail=False, methods=["get"], url_path="latest-invoice")
    def latest_invoice(self, request):
        last_bill = self.get_queryset().order_by("-id").first()
        next_number = 1 if last_bill is None else last_bill.id + 1

        return Response({"invoice_id": f"INV-{next_number:04d}"})


@owner_session_required
def subscription_admin_panel(request):
    today = timezone.localdate()
    plans = SubscriptionPlan.objects.all()
    subscriptions = BusinessSubscription.objects.select_related("business", "plan").all()
    subscribed_business_ids = subscriptions.values_list("business_id", flat=True)
    businesses_without_subscription = BusinessProfile.objects.exclude(
        id__in=subscribed_business_ids,
    ).order_by("name")

    metrics = {
        "total_businesses": BusinessProfile.objects.count(),
        "active": subscriptions.filter(status="active", ends_at__gte=today).count(),
        "trial": subscriptions.filter(status="trial", ends_at__gte=today).count(),
        "expired": subscriptions.filter(ends_at__lt=today).count(),
    }

    return render(
        request,
        "api/subscription_admin.html",
        {
            "businesses_without_subscription": businesses_without_subscription,
            "metrics": metrics,
            "plans": plans,
            "statuses": BusinessSubscription.STATUSES,
            "subscriptions": subscriptions,
            "today": today,
        },
    )


@owner_session_required
def subscription_admin_businesses(request):
    search_query = request.GET.get("q", "").strip()
    businesses = (
        BusinessProfile.objects.select_related("subscription__plan")
        .prefetch_related("users__user")
        .annotate(
            users_count=Count("users", distinct=True),
            products_count=Count("products", distinct=True),
            customers_count=Count("customers", distinct=True),
            bills_count=Count("bills", distinct=True),
        )
        .order_by("-created_at", "name")
    )

    if search_query:
        businesses = businesses.filter(
            Q(name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(gstin__icontains=search_query)
            | Q(users__user__username__icontains=search_query)
            | Q(users__user__email__icontains=search_query)
        ).distinct()

    today = timezone.localdate()
    all_businesses = BusinessProfile.objects.all()
    subscriptions = BusinessSubscription.objects.all()
    plans = SubscriptionPlan.objects.all()
    metrics = {
        "total": all_businesses.count(),
        "with_subscription": subscriptions.count(),
        "active": subscriptions.filter(
            status__in=("active", "trial"),
            ends_at__gte=today,
        ).count(),
        "without_subscription": all_businesses.filter(subscription__isnull=True).count(),
    }

    return render(
        request,
        "api/subscription_admin_businesses.html",
        {
            "businesses": businesses,
            "metrics": metrics,
            "plans": plans,
            "search_query": search_query,
            "statuses": BusinessSubscription.STATUSES,
            "today": today,
        },
    )


def subscription_admin_logout(request):
    logout(request)
    request.session.flush()
    return redirect("/subscription-admin/login/")


@owner_session_required
@require_http_methods(["POST"])
def subscription_plan_create(request):
    SubscriptionPlan.objects.create(
        name=request.POST.get("name", "").strip(),
        code=request.POST.get("code", "").strip().lower(),
        price=request.POST.get("price") or 0,
        billing_cycle=request.POST.get("billing_cycle", "monthly"),
        max_users=request.POST.get("max_users") or 1,
        max_products=request.POST.get("max_products") or 100,
        description=request.POST.get("description", "").strip(),
        is_active=request.POST.get("is_active") == "on",
    )
    return redirect("subscription-admin-panel")


@owner_session_required
@require_http_methods(["POST"])
def business_subscription_save(request):
    subscription_id = request.POST.get("subscription_id")
    business = get_object_or_404(BusinessProfile, id=request.POST.get("business"))
    plan = get_object_or_404(SubscriptionPlan, id=request.POST.get("plan"))

    values = {
        "business": business,
        "plan": plan,
        "status": request.POST.get("status", "trial"),
        "starts_at": parse_date(request.POST.get("starts_at")) or timezone.localdate(),
        "ends_at": parse_date(request.POST.get("ends_at")) or timezone.localdate(),
        "trial_ends_at": parse_date(request.POST.get("trial_ends_at")),
        "seats": request.POST.get("seats") or 1,
        "notes": request.POST.get("notes", "").strip(),
    }

    if subscription_id:
        subscription = get_object_or_404(BusinessSubscription, id=subscription_id)
        for field, value in values.items():
            setattr(subscription, field, value)
        subscription.save()
    else:
        BusinessSubscription.objects.update_or_create(
            business=business,
            defaults={key: value for key, value in values.items() if key != "business"},
        )

    if request.POST.get("redirect_to") == "businesses":
        return redirect("subscription-admin-businesses")

    return redirect("subscription-admin-panel")


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health_check(request):
    return Response({"status": "ok"})


def parse_version(value):
    parts = []
    for part in str(value or "").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


def compare_versions(left, right):
    left_parts = list(parse_version(left))
    right_parts = list(parse_version(right))
    max_length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_length - len(left_parts)))
    right_parts.extend([0] * (max_length - len(right_parts)))

    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def app_update_check(request):
    platform = request.query_params.get("platform", "android").lower()
    prefix = "IOS" if platform == "ios" else "ANDROID"

    latest_version = os.environ.get(f"{prefix}_LATEST_VERSION", "1.0")
    latest_build = parse_int(os.environ.get(f"{prefix}_LATEST_BUILD"), 1)
    minimum_supported_version = os.environ.get(f"{prefix}_MIN_SUPPORTED_VERSION", "1.0")
    minimum_supported_build = parse_int(os.environ.get(f"{prefix}_MIN_SUPPORTED_BUILD"), 1)
    current_version = request.query_params.get("version", "0")
    current_build = parse_int(request.query_params.get("build"), 0)

    update_available = (
        current_build < latest_build
        or compare_versions(current_version, latest_version) < 0
    )
    update_required = (
        current_build < minimum_supported_build
        or compare_versions(current_version, minimum_supported_version) < 0
    )
    release_notes = os.environ.get(
        f"{prefix}_RELEASE_NOTES",
        "Bug fixes and performance improvements.",
    )

    return Response(
        {
            "platform": platform,
            "current_version": current_version,
            "current_build": current_build,
            "latest_version": latest_version,
            "latest_build": latest_build,
            "minimum_supported_version": minimum_supported_version,
            "minimum_supported_build": minimum_supported_build,
            "update_available": update_available,
            "update_required": update_required,
            "title": os.environ.get(f"{prefix}_UPDATE_TITLE", "Update available"),
            "message": os.environ.get(
                f"{prefix}_UPDATE_MESSAGE",
                "A newer version of NuvaBill is available.",
            ),
            "store_url": os.environ.get(
                f"{prefix}_UPDATE_URL",
                "https://play.google.com/store/apps/details?id=com.nuvabill",
            ),
            "release_notes": [
                note.strip()
                for note in release_notes.split("|")
                if note.strip()
            ],
        },
    )


LEGAL_DOCUMENTS = {
    "terms": {
        "title": "Terms and Conditions",
        "version": "1.0",
        "effective_date": "2026-05-18",
        "sections": [
            {
                "heading": "Use of NuvaBill",
                "body": "NuvaBill is provided for point-of-sale billing, product, customer, report, and subscription management. You are responsible for the accuracy of business, tax, product, customer, and billing information entered in the app.",
            },
            {
                "heading": "Account Access",
                "body": "You must keep your login credentials and registered mobile number secure. Activity performed from your account may be treated as activity authorized by you.",
            },
            {
                "heading": "Payments and Subscriptions",
                "body": "Paid subscription plans, trial periods, renewal dates, product limits, and user limits are shown in the app or admin panel. Payment gateway processing is handled by the configured payment provider.",
            },
            {
                "heading": "Service Availability",
                "body": "We aim to keep the service available, but access may be interrupted because of maintenance, network issues, infrastructure outages, or third-party service failures.",
            },
            {
                "heading": "Data Responsibility",
                "body": "You are responsible for reviewing generated bills, reports, GST details, and customer records before using them for business, accounting, or compliance purposes.",
            },
        ],
    },
    "privacy": {
        "title": "Privacy Policy",
        "version": "1.0",
        "effective_date": "2026-05-18",
        "sections": [
            {
                "heading": "Information We Collect",
                "body": "We collect account details, business profile information, phone number, product records, customer records, bills, reports, subscription information, and payment status needed to operate the app.",
            },
            {
                "heading": "How We Use Information",
                "body": "Information is used to provide login, billing, inventory, customer management, reporting, subscription, support, and security features.",
            },
            {
                "heading": "Sharing",
                "body": "We do not sell your business data. Information may be shared with infrastructure, authentication, payment, analytics, or support providers only when needed to run the service.",
            },
            {
                "heading": "Retention and Deletion",
                "body": "You can request account deletion from the app. Deleting the account removes the login and, when no other users are linked to the business, removes associated business data.",
            },
            {
                "heading": "Contact",
                "body": "For privacy or account questions, contact the NuvaBill support team through your official support channel.",
            },
        ],
    },
}


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def legal_document(request, document_type):
    document = LEGAL_DOCUMENTS.get(document_type)
    if not document:
        return Response({"detail": "Legal document not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(document)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def support_contact(request):
    return Response(
        {
            "phone": "7219575187",
            "email": "supportnuvabill@gmail.com",
            "label": "NuvaBill Support",
        },
    )


@require_http_methods(["GET", "POST"])
def account_delete_request(request):
    support_email = "supportnuvabill@gmail.com"
    context = {
        "support_email": support_email,
        "submitted": False,
        "mail_failed": False,
    }

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        business_name = request.POST.get("business_name", "").strip()
        note = request.POST.get("note", "").strip()

        message = "\n".join(
            [
                "NuvaBill account deletion request",
                "",
                f"Name: {full_name or '-'}",
                f"Registered phone: {phone or '-'}",
                f"Email: {email or '-'}",
                f"Business/shop name: {business_name or '-'}",
                f"Additional note: {note or '-'}",
            ],
        )

        try:
            send_mail(
                "NuvaBill account deletion request",
                message,
                getattr(settings, "DEFAULT_FROM_EMAIL", support_email),
                [support_email],
                fail_silently=False,
            )
        except Exception:
            context["mail_failed"] = True

        context["submitted"] = True

    return render(request, "api/account_delete_request.html", context)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def product_unit_types(request):
    return Response(
        [
            {"value": value, "label": label}
            for value, label in Product.UNIT_TYPES
        ],
    )


@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def account_delete(request):
    user = request.user
    business = get_request_business(request)
    business_id = business.id if business else None
    business_user_count = business.users.count() if business else 0

    user.delete()

    if business and business_user_count <= 1:
        business.delete()

    return Response(
        {
            "detail": "Account deleted successfully.",
            "business_deleted": bool(business_id and business_user_count <= 1),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def subscription_plans(request):
    plans = SubscriptionPlan.objects.filter(is_active=True)
    return Response(SubscriptionPlanSerializer(plans, many=True).data)


@api_view(["GET", "POST"])
@permission_classes([permissions.AllowAny])
def app_subscription(request):
    if request.method == "GET":
        business_id = request.query_params.get("business_id")
        phone = request.query_params.get("phone", "").strip()

        subscription = BusinessSubscription.objects.select_related("business", "plan")
        if business_id:
            subscription = subscription.filter(business_id=business_id).first()
        elif phone:
            subscription = subscription.filter(business__phone=phone).first()
        else:
            subscription = None

        if not subscription:
            return Response({"detail": "No subscription found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(BusinessSubscriptionSerializer(subscription).data)

    plan_code = request.data.get("plan_code")
    if plan_code:
        plan, plan_data = get_app_subscription_plan(plan_code)
        if not plan:
            return Response({"detail": "Invalid subscription plan."}, status=status.HTTP_400_BAD_REQUEST)
    else:
        plan = get_object_or_404(SubscriptionPlan, id=request.data.get("plan"))
        days_by_cycle = {"monthly": 30, "quarterly": 90, "yearly": 365}
        plan_data = {
            "duration_days": days_by_cycle.get(plan.billing_cycle, 30),
            "status": "active",
            "trial": False,
        }

    if not plan_data.get("trial") and plan.price > 0:
        return Response(
            {"detail": "Paid plans must be activated after Razorpay payment verification."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    business = get_or_create_subscription_business(request.data)
    subscription = activate_business_subscription(
        business,
        plan,
        plan_data,
        seats=request.data.get("seats") or 1,
    )

    return Response(BusinessSubscriptionSerializer(subscription).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def create_subscription_razorpay_order(request):
    plan_code = request.data.get("plan_code")
    plan, plan_data = get_paid_app_plan(plan_code)
    if not plan:
        return Response(
            {"detail": "Razorpay payment is available only for paid app plans."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    business = get_or_create_subscription_business(request.data)
    amount = int(plan.price * Decimal("100"))
    currency = settings.RAZORPAY_CURRENCY
    receipt = f"sub_{business.id}_{uuid.uuid4().hex[:24]}"

    try:
        razorpay_order = create_razorpay_order(
            amount,
            currency,
            receipt,
            {
                "business_id": str(business.id),
                "plan_code": plan.code,
                "plan_name": plan.name,
            },
        )
    except RuntimeError as caught_error:
        return Response({"detail": str(caught_error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as caught_error:
        return Response(
            {"detail": f"Could not create Razorpay order. {caught_error}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    payment_order = SubscriptionPaymentOrder.objects.create(
        business=business,
        plan=plan,
        razorpay_order_id=razorpay_order["id"],
        amount=amount,
        currency=currency,
        receipt=receipt,
    )

    return Response(
        {
            "key_id": settings.RAZORPAY_KEY_ID,
            "order_id": payment_order.razorpay_order_id,
            "amount": payment_order.amount,
            "currency": payment_order.currency,
            "receipt": payment_order.receipt,
            "plan_code": plan.code,
            "plan_name": plan.name,
            "business_name": business.name,
            "business_phone": business.phone,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def verify_subscription_razorpay_payment(request):
    order_id = request.data.get("razorpay_order_id")
    payment_id = request.data.get("razorpay_payment_id")
    signature = request.data.get("razorpay_signature")

    if not order_id or not payment_id or not signature:
        return Response(
            {"detail": "Razorpay order, payment, and signature are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payment_order = get_object_or_404(
        SubscriptionPaymentOrder.objects.select_related("business", "plan"),
        razorpay_order_id=order_id,
    )
    if payment_order.status == "paid":
        subscription = payment_order.business.subscription
        return Response(BusinessSubscriptionSerializer(subscription).data)

    if not verify_razorpay_signature(order_id, payment_id, signature):
        payment_order.status = "failed"
        payment_order.save(update_fields=("status", "updated_at"))
        return Response({"detail": "Invalid Razorpay payment signature."}, status=status.HTTP_400_BAD_REQUEST)

    _, plan_data = get_app_subscription_plan(payment_order.plan.code)
    subscription = activate_business_subscription(
        payment_order.business,
        payment_order.plan,
        plan_data,
        notes=f"Activated after Razorpay payment {payment_id}.",
    )
    payment_order.razorpay_payment_id = payment_id
    payment_order.status = "paid"
    payment_order.save(update_fields=("razorpay_payment_id", "status", "updated_at"))

    return Response(BusinessSubscriptionSerializer(subscription).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def dashboard_summary(request):
    business = require_request_business(request)
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    today_start, today_end = get_local_day_range(today)
    yesterday_start, yesterday_end = get_local_day_range(yesterday)

    today_bills = Bill.objects.filter(
        business=business,
        created_at__gte=today_start,
        created_at__lt=today_end,
    )
    yesterday_bills = Bill.objects.filter(
        business=business,
        created_at__gte=yesterday_start,
        created_at__lt=yesterday_end,
    )

    today_sales = today_bills.aggregate(total=Sum("grand_total"))["total"] or 0
    yesterday_sales = yesterday_bills.aggregate(total=Sum("grand_total"))["total"] or 0

    if yesterday_sales:
        sales_change = ((today_sales - yesterday_sales) / yesterday_sales) * 100
    else:
        sales_change = 0

    return Response(
        {
            "today_sales": today_sales,
            "total_orders": today_bills.count(),
            "sales_change_percent": round(sales_change, 2),
            "products_count": Product.objects.filter(business=business).count(),
            "customers_count": Customer.objects.filter(business=business).count(),
            "categories_count": Category.objects.filter(business=business).count(),
        },
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def reports_summary(request):
    business = require_request_business(request)
    period = normalize_report_period(request)
    start_day, end_day, start_at, end_at, _ = get_report_period_range(period)

    bills = Bill.objects.filter(
        business=business,
        created_at__gte=start_at,
        created_at__lt=end_at,
    )
    bill_ids = bills.values_list("id", flat=True)
    total_sales = bills.aggregate(total=Sum("grand_total"))["total"] or 0
    item_total = ExpressionWrapper(
        F("price") * F("quantity"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    payment_breakdown = bills.values("payment_mode").annotate(
        count=Count("id"),
        total=Sum("grand_total"),
    )
    top_products = (
        BillItem.objects.filter(bill_id__in=bill_ids)
        .values("name")
        .annotate(
            sold_quantity=Sum("quantity"),
            total=Sum(item_total),
            image_url=Max("image_url"),
        )
        .order_by("-sold_quantity")[:5]
    )
    top_products_data = [
        {
            "name": item["name"],
            "quantity": item["sold_quantity"],
            "total": item["total"],
            "image_url": item["image_url"],
        }
        for item in top_products
    ]

    return Response(
        {
            "period": period,
            "start_date": start_day,
            "end_date": end_day,
            "month_start": start_day,
            "total_sales": total_sales,
            "total_orders": bills.count(),
            "payment_breakdown": list(payment_breakdown),
            "top_products": top_products_data,
        },
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def bill_pdf(request, bill_id):
    business = get_pdf_request_business(request)
    if not business:
        return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

    bill = get_object_or_404(
        Bill.objects.prefetch_related("items").select_related(
            "business",
            "customer",
            "credit_customer",
        ),
        id=bill_id,
        business=business,
    )
    filename = f"bill-{bill.invoice_id}.pdf"
    response = HttpResponse(build_receipt_pdf(build_bill_pdf_lines(bill)), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def credit_payment_pdf(request, payment_id):
    business = get_pdf_request_business(request)
    if not business:
        return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

    if business.business_type != "Kirana shop":
        return Response(
            {"detail": "This feature is available only for Kirana shop businesses."},
            status=status.HTTP_403_FORBIDDEN,
        )

    payment = get_object_or_404(
        CreditPayment.objects.select_related("business", "customer", "bill"),
        id=payment_id,
        business=business,
    )
    filename = f"payment-{payment.receipt_id or f'PAY-{payment.id:04d}'}.pdf"
    response = HttpResponse(
        build_receipt_pdf(build_credit_payment_pdf_lines(payment)),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def reports_download(request):
    business = get_pdf_request_business(request)
    if not business:
        return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

    period = normalize_report_period(request)
    start_day, end_day, start_at, end_at, label = get_report_period_range(period)
    bills = (
        Bill.objects.select_related("credit_customer")
        .prefetch_related("items")
        .filter(
            business=business,
            created_at__gte=start_at,
            created_at__lt=end_at,
        )
    )
    total_sales = bills.aggregate(total=Sum("grand_total"))["total"] or 0
    paid_total = bills.aggregate(total=Sum("paid_amount"))["total"] or 0
    remaining_total = bills.aggregate(total=Sum("remaining_amount"))["total"] or 0
    credit_bills = bills.filter(payment_mode="Credit")
    non_credit_bills = bills.exclude(payment_mode="Credit")
    paid_rows = []
    credit_rows = []

    for bill in non_credit_bills.order_by("created_at", "id"):
        paid_rows.append(
            {
                "invoice": bill.invoice_id,
                "item": report_bill_items(bill),
                "date": timezone.localtime(bill.created_at).strftime("%d %b %Y"),
                "total": money(bill.grand_total),
            },
        )

    for bill in credit_bills.order_by("created_at", "id"):
        credit_rows.append(
            {
                "invoice": bill.invoice_id,
                "customer_name": bill.credit_customer.name if bill.credit_customer else "",
                "customer_phone": bill.credit_customer.phone if bill.credit_customer else "",
                "item": report_bill_items(bill),
                "date": timezone.localtime(bill.created_at).strftime("%d %b %Y"),
                "total": money(bill.grand_total),
                "paid": money(bill.paid_amount),
                "remaining": money(bill.remaining_amount),
            },
        )

    tables = [
        {
            "title": "Paid Bills",
            "columns": (
                ("Invoice No", 120, "invoice"),
                ("Item", 360, "item"),
                ("Date", 110, "date"),
                ("Total Amount", 140, "total", "right"),
            ),
            "rows": paid_rows,
            "min_rows": 4,
        },
        {
            "title": "Credit Bills",
            "columns": (
                ("Invoice No", 75, "invoice"),
                ("Customer Name", 105, "customer_name"),
                ("Phone", 75, "customer_phone"),
                ("Item", 155, "item"),
                ("Date", 70, "date"),
                ("Total Amount", 85, "total", "right"),
                ("Paid Amount", 80, "paid", "right"),
                ("Remaining Amount", 95, "remaining", "right"),
            ),
            "rows": credit_rows,
            "min_rows": 4,
        },
    ]
    totals = [
        ("Total bills", str(bills.count())),
        ("Total amount", money(total_sales)),
        ("Paid amount", money(paid_total)),
        ("Remaining amount", money(remaining_total)),
    ]
    pdf = build_report_table_pdf(
        f"{business.name} {label} Sales Report",
        f"Period: {start_day:%d %b %Y} to {end_day:%d %b %Y}",
        f"Generated: {timezone.localtime():%d %b %Y, %I:%M %p}",
        tables,
        totals,
    )

    filename = f"{period}-sales-report-{end_day:%Y-%m-%d}.pdf"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
