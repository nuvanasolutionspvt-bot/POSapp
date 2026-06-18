from decimal import Decimal

from django.db import migrations


def refresh_bill_credit_totals(bill):
    bill.remaining_amount = max(
        Decimal("0.00"),
        Decimal(bill.grand_total or 0) - Decimal(bill.paid_amount or 0),
    )
    bill.total_balance = Decimal(bill.previous_balance or 0) + Decimal(bill.remaining_amount or 0)
    bill.is_paid = bill.remaining_amount <= 0
    bill.save(
        update_fields=(
            "paid_amount",
            "remaining_amount",
            "total_balance",
            "is_paid",
            "updated_at",
        ),
    )


def backfill_credit_payment_allocations(apps, schema_editor):
    Bill = apps.get_model("api", "Bill")
    CreditPayment = apps.get_model("api", "CreditPayment")
    CreditPaymentAllocation = apps.get_model("api", "CreditPaymentAllocation")

    allocated_payment_ids = CreditPaymentAllocation.objects.values_list("payment_id", flat=True)
    payments = (
        CreditPayment.objects.exclude(id__in=allocated_payment_ids)
        .filter(amount__gt=0)
        .order_by("created_at", "id")
    )

    for payment in payments:
        remaining_payment = Decimal(payment.amount or 0)
        first_bill = None
        bills = Bill.objects.filter(
            business_id=payment.business_id,
            credit_customer_id=payment.customer_id,
            payment_mode="Credit",
            remaining_amount__gt=0,
            created_at__lte=payment.created_at,
        ).order_by("created_at", "id")

        if payment.bill_id:
            bills = bills.filter(id=payment.bill_id)

        for bill in bills:
            if remaining_payment <= 0:
                break

            allocation_amount = min(remaining_payment, Decimal(bill.remaining_amount or 0))
            if allocation_amount <= 0:
                continue

            bill.paid_amount = Decimal(bill.paid_amount or 0) + allocation_amount
            refresh_bill_credit_totals(bill)
            CreditPaymentAllocation.objects.create(
                payment_id=payment.id,
                bill_id=bill.id,
                amount=allocation_amount,
            )

            if first_bill is None:
                first_bill = bill

            remaining_payment -= allocation_amount

        if first_bill and not payment.bill_id:
            payment.bill_id = first_bill.id
            payment.save(update_fields=("bill", "updated_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0015_creditpaymentallocation"),
    ]

    operations = [
        migrations.RunPython(backfill_credit_payment_allocations, migrations.RunPython.noop),
    ]
