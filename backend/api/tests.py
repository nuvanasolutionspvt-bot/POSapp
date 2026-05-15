from django.test import RequestFactory, TestCase

from .serializers import BillItemSerializer


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
