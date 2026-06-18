from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import BusinessProfile, BusinessSubscription, CreditCustomer, SubscriptionPlan, UserProfile
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
        serializer.save(business=self.business)
        self.credit_customer.refresh_from_db()

        self.assertEqual(self.credit_customer.current_balance, Decimal("375.00"))


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
        self.assertTrue(SubscriptionPlan.objects.filter(code="monthly_499").exists())

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
