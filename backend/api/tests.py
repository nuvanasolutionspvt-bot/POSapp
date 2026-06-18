from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    Bill,
    BillItem,
    BusinessProfile,
    BusinessSubscription,
    CreditCustomer,
    CreditPayment,
    SubscriptionPlan,
    UserProfile,
)
from .serializers import BillItemSerializer, BillSerializer, CreditPaymentSerializer


class BillItemSerializerTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().post("/api/bills/", HTTP_HOST="192.168.1.12:8000")

    def test_relative_product_image_is_saved_as_full_media_url(self):
        serializer = BillItemSerializer(
            data={
                "name": "Test item",
                "price": "10.00",
                "quantity": 1,
                "image": "products/1000498526_1tdezC2.jpg",
            },
            context={"request": self.request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["image_url"],
            "http://192.168.1.12:8000/media/products/1000498526_1tdezC2.jpg",
        )

    def test_media_path_image_is_saved_as_full_media_url(self):
        serializer = BillItemSerializer(
            data={
                "name": "Test item",
                "price": "10.00",
                "quantity": 1,
                "image": "/media/products/1000498526_1tdezC2.jpg",
            },
            context={"request": self.request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["image_url"],
            "http://192.168.1.12:8000/media/products/1000498526_1tdezC2.jpg",
        )

    def test_fractional_quantity_is_valid_for_weighted_items(self):
        serializer = BillItemSerializer(
            data={
                "name": "Rice",
                "price": "80.00",
                "quantity": "1.250",
                "image": "",
            },
            context={"request": self.request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["quantity"], Decimal("1.250"))


class CreditBillingSerializerTests(TestCase):
    def setUp(self):
        self.business = BusinessProfile.objects.create(
            name="Kirana Store",
            business_type="Kirana shop",
        )
        self.credit_customer = CreditCustomer.objects.create(
            business=self.business,
            name="Ramesh",
            phone="9876543210",
            current_balance=Decimal("500.00"),
        )

    def test_non_credit_bills_accept_modified_decimal_quantities(self):
        for payment_mode in ("Cash", "UPI", "Card"):
            with self.subTest(payment_mode=payment_mode):
                serializer = BillSerializer(
                    data={
                        "invoiceId": f"INV-{payment_mode}",
                        "items": [
                            {
                                "name": "Rice",
                                "price": "80.00",
                                "quantity": "1.500",
                                "image": "",
                            },
                        ],
                        "paymentMode": payment_mode,
                        "subtotal": "120.00",
                        "discount": "0.00",
                        "tax": "0.00",
                        "grandTotal": "120.00",
                    },
                )

                self.assertTrue(serializer.is_valid(), serializer.errors)
                bill = serializer.save(business=self.business)
                item = bill.items.get()

                self.assertEqual(bill.payment_mode, payment_mode)
                self.assertEqual(item.quantity, Decimal("1.500"))

    def test_credit_bill_updates_customer_balance(self):
        serializer = BillSerializer(
            data={
                "invoiceId": "INV-CREDIT-1",
                "items": [
                    {
                        "name": "Rice",
                        "price": "80.00",
                        "quantity": "2.000",
                        "image": "",
                    },
                ],
                "paymentMode": "Credit",
                "subtotal": "160.00",
                "discount": "0.00",
                "tax": "0.00",
                "grandTotal": "160.00",
                "creditCustomer": self.credit_customer.id,
                "paidAmount": "60.00",
            },
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        bill = serializer.save(business=self.business)
        self.credit_customer.refresh_from_db()

        self.assertEqual(bill.remaining_amount, Decimal("100.00"))
        self.assertEqual(bill.previous_balance, Decimal("500.00"))
        self.assertEqual(bill.total_balance, Decimal("600.00"))
        self.assertEqual(self.credit_customer.current_balance, Decimal("600.00"))

    def test_credit_payment_reduces_customer_balance(self):
        serializer = CreditPaymentSerializer(
            data={
                "customer": self.credit_customer.id,
                "amount": "125.00",
                "note": "Partial payment",
            },
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save(business=self.business)
        self.credit_customer.refresh_from_db()

        self.assertEqual(self.credit_customer.current_balance, Decimal("375.00"))
        self.assertEqual(payment.receipt_id, f"PAY-{payment.id:04d}")
        self.assertEqual(payment.payment_mode, "Cash")
        self.assertEqual(payment.previous_balance, Decimal("500.00"))
        self.assertEqual(payment.remaining_balance, Decimal("375.00"))


class CreditPaymentViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="credit-payment-user", password="Password123")
        self.business = BusinessProfile.objects.create(
            name="Ledger Store",
            business_type="Kirana shop",
            phone="9876543230",
        )
        UserProfile.objects.create(
            user=self.user,
            phone="9876543230",
            business_profile=self.business,
        )
        self.credit_customer = CreditCustomer.objects.create(
            business=self.business,
            name="Suresh",
            phone="9876543231",
            current_balance=Decimal("500.00"),
        )
        self.client.force_authenticate(user=self.user)

    def test_create_credit_payment_stores_receipt_and_balance_snapshot(self):
        response = self.client.post(
            "/api/credit-payments/",
            {
                "customer": self.credit_customer.id,
                "amount": "125.00",
                "paymentMode": "UPI",
                "note": "PhonePe",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.credit_customer.refresh_from_db()

        self.assertEqual(response.data["receiptId"], f"PAY-{response.data['id']:04d}")
        self.assertEqual(response.data["paymentMode"], "UPI")
        self.assertEqual(response.data["previousBalance"], "500.00")
        self.assertEqual(response.data["remainingBalance"], "375.00")
        self.assertEqual(self.credit_customer.current_balance, Decimal("375.00"))

    def test_customer_payment_settles_pending_credit_bill(self):
        bill = Bill.objects.create(
            business=self.business,
            invoice_id="INV-PAY-1",
            payment_mode="Credit",
            credit_customer=self.credit_customer,
            subtotal=Decimal("2450.00"),
            grand_total=Decimal("2450.00"),
            paid_amount=Decimal("0.00"),
            remaining_amount=Decimal("2450.00"),
            previous_balance=Decimal("0.00"),
            total_balance=Decimal("2450.00"),
            is_paid=False,
        )
        self.credit_customer.current_balance = Decimal("2450.00")
        self.credit_customer.save(update_fields=("current_balance", "updated_at"))

        response = self.client.post(
            "/api/credit-payments/",
            {
                "customer": self.credit_customer.id,
                "amount": "2450.00",
                "paymentMode": "Cash",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.credit_customer.refresh_from_db()
        bill.refresh_from_db()

        self.assertEqual(self.credit_customer.current_balance, Decimal("0.00"))
        self.assertEqual(bill.paid_amount, Decimal("2450.00"))
        self.assertEqual(bill.remaining_amount, Decimal("0.00"))
        self.assertEqual(bill.total_balance, Decimal("0.00"))
        self.assertTrue(bill.is_paid)
        self.assertEqual(response.data["bill"], bill.id)

        bill_response = self.client.get(f"/api/bills/{bill.id}/")
        self.assertEqual(bill_response.status_code, 200, bill_response.data)
        self.assertEqual(bill_response.data["remainingAmount"], "0.00")
        self.assertTrue(bill_response.data["isPaid"])

    def test_modifying_customer_payment_recalculates_settled_bill(self):
        bill = Bill.objects.create(
            business=self.business,
            invoice_id="INV-PAY-2",
            payment_mode="Credit",
            credit_customer=self.credit_customer,
            subtotal=Decimal("2450.00"),
            grand_total=Decimal("2450.00"),
            paid_amount=Decimal("0.00"),
            remaining_amount=Decimal("2450.00"),
            previous_balance=Decimal("0.00"),
            total_balance=Decimal("2450.00"),
            is_paid=False,
        )
        self.credit_customer.current_balance = Decimal("2450.00")
        self.credit_customer.save(update_fields=("current_balance", "updated_at"))

        create_response = self.client.post(
            "/api/credit-payments/",
            {
                "customer": self.credit_customer.id,
                "amount": "1000.00",
                "paymentMode": "Cash",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)

        update_response = self.client.patch(
            f"/api/credit-payments/{create_response.data['id']}/",
            {
                "amount": "1500.00",
                "paymentMode": "UPI",
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200, update_response.data)
        self.credit_customer.refresh_from_db()
        bill.refresh_from_db()

        self.assertEqual(self.credit_customer.current_balance, Decimal("950.00"))
        self.assertEqual(bill.paid_amount, Decimal("1500.00"))
        self.assertEqual(bill.remaining_amount, Decimal("950.00"))
        self.assertEqual(bill.total_balance, Decimal("950.00"))
        self.assertFalse(bill.is_paid)

    def test_update_credit_payment_recalculates_customer_balance(self):
        payment = CreditPayment.objects.create(
            business=self.business,
            customer=self.credit_customer,
            receipt_id="PAY-0001",
            payment_mode="Cash",
            amount=Decimal("100.00"),
            previous_balance=Decimal("500.00"),
            remaining_balance=Decimal("400.00"),
        )
        self.credit_customer.current_balance = Decimal("400.00")
        self.credit_customer.save(update_fields=("current_balance", "updated_at"))

        response = self.client.patch(
            f"/api/credit-payments/{payment.id}/",
            {
                "amount": "150.00",
                "paymentMode": "Card",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.credit_customer.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.payment_mode, "Card")
        self.assertEqual(payment.previous_balance, Decimal("500.00"))
        self.assertEqual(payment.remaining_balance, Decimal("350.00"))
        self.assertEqual(self.credit_customer.current_balance, Decimal("350.00"))

    def test_credit_customer_ledger_combines_bills_and_payments(self):
        bill = Bill.objects.create(
            business=self.business,
            invoice_id="INV-LEDGER-1",
            payment_mode="Credit",
            credit_customer=self.credit_customer,
            subtotal=Decimal("200.00"),
            grand_total=Decimal("200.00"),
            paid_amount=Decimal("50.00"),
            remaining_amount=Decimal("150.00"),
            previous_balance=Decimal("500.00"),
            total_balance=Decimal("650.00"),
        )
        payment = CreditPayment.objects.create(
            business=self.business,
            customer=self.credit_customer,
            receipt_id="PAY-LEDGER-1",
            payment_mode="Cash",
            amount=Decimal("100.00"),
            previous_balance=Decimal("650.00"),
            remaining_balance=Decimal("550.00"),
        )
        self.credit_customer.current_balance = Decimal("550.00")
        self.credit_customer.save(update_fields=("current_balance", "updated_at"))

        response = self.client.get(f"/api/credit-customers/{self.credit_customer.id}/ledger/")

        self.assertEqual(response.status_code, 200, response.data)
        record_types = {record["type"] for record in response.data["results"]}
        self.assertEqual(record_types, {"bill", "payment"})
        bill_record = next(record for record in response.data["results"] if record["type"] == "bill")
        payment_record = next(record for record in response.data["results"] if record["type"] == "payment")

        self.assertEqual(bill_record["id"], bill.id)
        self.assertEqual(bill_record["invoiceId"], "INV-LEDGER-1")
        self.assertEqual(bill_record["balanceAfter"], Decimal("650.00"))
        self.assertEqual(payment_record["id"], payment.id)
        self.assertEqual(payment_record["receiptId"], "PAY-LEDGER-1")
        self.assertEqual(payment_record["balanceAfter"], Decimal("550.00"))


class BillViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bill-user", password="Password123")
        self.business = BusinessProfile.objects.create(
            name="API Store",
            business_type="Kirana shop",
            phone="9876543220",
        )
        UserProfile.objects.create(
            user=self.user,
            phone="9876543220",
            business_profile=self.business,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_bill_endpoint_accepts_modified_decimal_quantities(self):
        for payment_mode in ("Cash", "UPI", "Card"):
            with self.subTest(payment_mode=payment_mode):
                response = self.client.post(
                    "/api/bills/",
                    {
                        "invoiceId": f"API-{payment_mode}",
                        "items": [
                            {
                                "name": "Rice",
                                "price": "80.00",
                                "quantity": "1.500",
                                "image": "",
                            },
                        ],
                        "paymentMode": payment_mode,
                        "subtotal": "120.00",
                        "discount": "0.00",
                        "tax": "0.00",
                        "grandTotal": "120.00",
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["paymentMode"], payment_mode)
                self.assertEqual(response.data["items"][0]["quantity"], "1.500")


class ReportsDownloadTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="report-user", password="Password123")
        self.business = BusinessProfile.objects.create(
            name="Report Store",
            business_type="Kirana shop",
            phone="9876543240",
        )
        UserProfile.objects.create(
            user=self.user,
            phone="9876543240",
            business_profile=self.business,
        )
        self.client.force_authenticate(user=self.user)

    def test_daily_report_pdf_contains_bill_tables_and_totals(self):
        credit_customer = CreditCustomer.objects.create(
            business=self.business,
            name="Credit Buyer",
            phone="9998887776",
            current_balance=Decimal("50.00"),
        )
        cash_bill = Bill.objects.create(
            business=self.business,
            invoice_id="INV-CASH",
            payment_mode="Cash",
            subtotal=Decimal("100.00"),
            grand_total=Decimal("100.00"),
        )
        BillItem.objects.create(
            bill=cash_bill,
            name="Sugar",
            price=Decimal("100.00"),
            quantity=Decimal("1.000"),
        )
        credit_bill = Bill.objects.create(
            business=self.business,
            invoice_id="INV-CREDIT",
            payment_mode="Credit",
            credit_customer=credit_customer,
            subtotal=Decimal("200.00"),
            grand_total=Decimal("200.00"),
            paid_amount=Decimal("150.00"),
            remaining_amount=Decimal("50.00"),
            previous_balance=Decimal("0.00"),
            total_balance=Decimal("50.00"),
            is_paid=False,
        )
        BillItem.objects.create(
            bill=credit_bill,
            name="Rice",
            price=Decimal("200.00"),
            quantity=Decimal("1.000"),
        )

        response = self.client.get("/api/reports/download/?period=daily")
        content = response.content.decode("latin-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Invoice No", content)
        self.assertIn("Total Amount", content)
        self.assertIn("Paid Amount", content)
        self.assertIn("Remaining Amount", content)
        self.assertIn("Customer Name", content)
        self.assertIn("Phone", content)
        self.assertIn("INV-CASH", content)
        self.assertIn("Sugar", content)
        self.assertIn("INV-CREDIT", content)
        self.assertIn("Credit Buyer", content)
        self.assertIn("9998887776", content)
        self.assertIn("Rice", content)
        self.assertIn("Total bills", content)
        self.assertIn("Total amount", content)
        self.assertIn("Paid amount", content)
        self.assertIn("Remaining amount", content)
        self.assertIn("Rs. 300.00", content)
        self.assertIn("Rs. 150.00", content)
        self.assertIn("Rs. 50.00", content)
        self.assertIn(" re f", content)
        self.assertIn(" l S", content)


class RegisterViewTests(APITestCase):
    def test_register_business_activates_7_day_trial_subscription(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "trialowner",
                "email": "owner@example.com",
                "password": "Password123",
                "phone": "9876543210",
                "business_name": "Trial Store",
                "business_type": "Others",
                "business_address": "Test address",
                "gstin": "",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        subscription = BusinessSubscription.objects.select_related("business", "plan").get(
            business__phone="9876543210",
        )
        expected_end_date = timezone.localdate() + timedelta(days=7)

        self.assertEqual(subscription.status, "trial")
        self.assertEqual(subscription.plan.code, "free_trial_7_days")
        self.assertEqual(subscription.starts_at, timezone.localdate())
        self.assertEqual(subscription.ends_at, expected_end_date)
        self.assertEqual(subscription.trial_ends_at, expected_end_date)
        self.assertEqual(response.data["subscription"]["status"], "trial")
        self.assertEqual(response.data["subscription"]["plan_name"], "Free Trial")

        trial_plan = SubscriptionPlan.objects.get(code="free_trial_7_days")
        self.assertEqual(trial_plan.max_products, 50)

    def test_register_business_with_paid_plan_does_not_activate_trial(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "paidowner",
                "email": "paid@example.com",
                "password": "Password123",
                "phone": "9876543211",
                "business_name": "Paid Store",
                "business_type": "Others",
                "business_address": "Test address",
                "gstin": "",
                "plan_code": "monthly_499",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["subscription"])
        self.assertFalse(
            BusinessSubscription.objects.filter(business__phone="9876543211").exists(),
        )
        monthly_plan = SubscriptionPlan.objects.get(code="monthly_499")
        self.assertEqual(monthly_plan.price, Decimal("299.00"))

    def test_register_accepts_app_payload_aliases_without_password(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "ownerName": "Alias Owner",
                "businessName": "Alias Store",
                "businessType": "Kirana Store",
                "planCode": "free trial",
                "businessAddress": "Alias address",
                "phoneNumber": "+91 98765 43212",
                "gstin": "",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["user"]["username"], "9876543212")
        self.assertEqual(response.data["business_profile"]["name"], "Alias Store")
        self.assertEqual(response.data["business_profile"]["businessType"], "Kirana shop")
        self.assertEqual(response.data["business_profile"]["ownerName"], "Alias Owner")
        self.assertEqual(response.data["subscription"]["plan_name"], "Free Trial")

    def test_register_unknown_business_type_falls_back_to_others(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "unknown-type-owner",
                "email": "",
                "password": "Password123",
                "phone": "9876543213",
                "business_name": "Unknown Type Store",
                "business_type": "Retail showroom",
                "plan_code": "free_trial_7_days",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["business_profile"]["businessType"], "Others")


class FirebaseLoginViewTests(APITestCase):
    @patch("api.views.verify_firebase_id_token")
    def test_firebase_token_verification_failure_returns_401_with_code(
        self,
        verify_firebase_id_token,
    ):
        verify_firebase_id_token.side_effect = ValueError("wrong audience")

        response = self.client.post(
            reverse("auth-firebase-login"),
            {"id_token": "invalid-token", "phone": "9876543210"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data["code"],
            "firebase_token_verification_failed",
        )

    @patch("api.views.verify_firebase_id_token")
    def test_firebase_login_accepts_matching_verified_phone(
        self,
        verify_firebase_id_token,
    ):
        user = User.objects.create_user(username="firebase-user", password="Password123")
        business = BusinessProfile.objects.create(name="Firebase Store", phone="9876543210")
        UserProfile.objects.create(
            user=user,
            phone="9876543210",
            business_profile=business,
        )
        verify_firebase_id_token.return_value = {
            "phone_number": "+919876543210",
        }

        response = self.client.post(
            reverse("auth-firebase-login"),
            {"id_token": "valid-token", "phone": "9876543210"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["phone"], "9876543210")


class SubscriptionAdminBusinessTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["subscription_owner_logged_in"] = True
        session.save()

    def test_businesses_page_lists_registered_business_details(self):
        user = User.objects.create_user(
            username="registered-owner",
            email="owner@example.com",
            password="Password123",
        )
        business = BusinessProfile.objects.create(
            name="Registered Store",
            business_type="Food shop",
            phone="9876543210",
            email="store@example.com",
            address="Pune",
            gstin="27ABCDE1234F1Z5",
        )
        UserProfile.objects.create(
            user=user,
            phone="9876543210",
            business_profile=business,
        )

        response = self.client.get(reverse("subscription-admin-businesses"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registered Store")
        self.assertContains(response, "registered-owner")
        self.assertContains(response, "27ABCDE1234F1Z5")
        self.assertContains(response, "Not assigned")

    def test_businesses_page_requires_owner_session(self):
        self.client.session.flush()

        response = self.client.get(reverse("subscription-admin-businesses"))

        self.assertRedirects(
            response,
            "/subscription-admin/login/",
            fetch_redirect_response=False,
        )

    def test_business_search_filters_registered_businesses(self):
        BusinessProfile.objects.create(name="Alpha Store", phone="9000000001")
        BusinessProfile.objects.create(name="Beta Store", phone="9000000002")

        response = self.client.get(
            reverse("subscription-admin-businesses"),
            {"q": "Alpha"},
        )

        self.assertContains(response, "Alpha Store")
        self.assertNotContains(response, "Beta Store")


class LegalAndAccountTests(APITestCase):
    def test_app_update_check_returns_update_available(self):
        with patch.dict(
            "os.environ",
            {
                "ANDROID_LATEST_VERSION": "1.2.0",
                "ANDROID_LATEST_BUILD": "5",
                "ANDROID_MIN_SUPPORTED_VERSION": "1.0.0",
                "ANDROID_MIN_SUPPORTED_BUILD": "1",
                "ANDROID_RELEASE_NOTES": "New reports|Bug fixes",
            },
        ):
            response = self.client.get(
                reverse("app-update-check"),
                {"platform": "android", "version": "1.0.0", "build": "1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["update_available"])
        self.assertFalse(response.data["update_required"])
        self.assertEqual(response.data["latest_version"], "1.2.0")
        self.assertEqual(response.data["latest_build"], 5)
        self.assertEqual(response.data["release_notes"], ["New reports", "Bug fixes"])

    def test_app_update_check_marks_required_below_min_supported_build(self):
        with patch.dict(
            "os.environ",
            {
                "ANDROID_LATEST_VERSION": "2.0.0",
                "ANDROID_LATEST_BUILD": "10",
                "ANDROID_MIN_SUPPORTED_VERSION": "1.5.0",
                "ANDROID_MIN_SUPPORTED_BUILD": "7",
            },
        ):
            response = self.client.get(
                reverse("app-update-check"),
                {"platform": "android", "version": "1.4.0", "build": "6"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["update_available"])
        self.assertTrue(response.data["update_required"])

    def test_terms_document_is_public(self):
        response = self.client.get(reverse("legal-document", kwargs={"document_type": "terms"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Terms and Conditions")
        self.assertGreater(len(response.data["sections"]), 0)

    def test_support_contact_is_public(self):
        response = self.client.get(reverse("support-contact"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone"], "7219575187")
        self.assertEqual(response.data["email"], "supportnuvabill@gmail.com")

    def test_product_unit_types_requires_auth_and_returns_choices(self):
        user = User.objects.create_user(username="unit-user", password="Password123")
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("product-unit-types"))

        self.assertEqual(response.status_code, 200)
        self.assertIn({"value": "pc", "label": "Piece"}, response.data)

    def test_account_delete_removes_user_and_single_user_business(self):
        user = User.objects.create_user(username="delete-user", password="Password123")
        business = BusinessProfile.objects.create(name="Delete Store", phone="9000000000")
        UserProfile.objects.create(user=user, phone="9000000000", business_profile=business)

        self.client.force_authenticate(user=user)
        response = self.client.delete(reverse("account-delete"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertFalse(BusinessProfile.objects.filter(id=business.id).exists())
        self.assertTrue(response.data["business_deleted"])
