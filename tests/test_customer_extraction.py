import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.api.routes.customer import extract_customers_endpoint
from app.schemas.customer import ExtractCustomersRequest


class CustomerExtractionRequestTests(unittest.IsolatedAsyncioTestCase):
    def test_file_url_accepts_one_url(self):
        payload = ExtractCustomersRequest(
            file_url="https://example.com/customer-list-1.jpeg"
        )

        self.assertEqual(len(payload.resolved_file_urls()), 1)

    def test_file_url_accepts_multiple_urls(self):
        payload = ExtractCustomersRequest(
            file_url=[
                "https://example.com/customer-list-1.jpeg",
                "https://example.com/customer-list-2.jpeg",
            ]
        )

        self.assertEqual(len(payload.resolved_file_urls()), 2)

    def test_file_url_rejects_an_empty_array(self):
        with self.assertRaises(ValidationError):
            ExtractCustomersRequest(file_url=[])

    @patch("app.api.routes.customer.extract_customers", new_callable=AsyncMock)
    async def test_route_forwards_every_url_to_customer_extractor(self, extractor):
        extractor.return_value = {
            "success": True,
            "source_file_urls": [
                "https://example.com/customer-list-1.jpeg",
                "https://example.com/customer-list-2.jpeg",
            ],
            "customers": [],
            "unresolved_records": [],
            "raw_ocr_text": "",
        }
        payload = ExtractCustomersRequest(
            file_url=[
                "https://example.com/customer-list-1.jpeg",
                "https://example.com/customer-list-2.jpeg",
            ]
        )

        await extract_customers_endpoint(payload)

        extractor.assert_awaited_once_with(
            [
                "https://example.com/customer-list-1.jpeg",
                "https://example.com/customer-list-2.jpeg",
            ]
        )


if __name__ == "__main__":
    unittest.main()
