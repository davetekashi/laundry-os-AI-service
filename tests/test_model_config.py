import unittest

from app.core.config import Settings


REQUIRED_SETTINGS = {
    "OPENAI_API_KEY": "test-openai-key",
    "MONGODB_URI": "mongodb://localhost/test",
    "R2_ACCESS_KEY_ID": "test-r2-key",
    "R2_SECRET_ACCESS_KEY": "test-r2-secret",
    "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
    "R2_BUCKET_NAME": "test-bucket",
}


class ModelConfigurationTests(unittest.TestCase):
    def test_all_openai_workloads_default_to_gpt_4_1(self):
        settings = Settings.model_validate(REQUIRED_SETTINGS)

        self.assertEqual(settings.openai_chat_model, "gpt-4.1")
        self.assertEqual(settings.openai_matching_model, "gpt-4.1")
        self.assertEqual(settings.openai_vision_model, "gpt-4.1")

    def test_each_workload_can_be_overridden_independently(self):
        settings = Settings.model_validate(
            {
                **REQUIRED_SETTINGS,
                "OPENAI_CHAT_MODEL": "chat-override",
                "OPENAI_MATCHING_MODEL": "matching-override",
                "OPENAI_VISION_MODEL": "vision-override",
            }
        )

        self.assertEqual(settings.openai_chat_model, "chat-override")
        self.assertEqual(settings.openai_matching_model, "matching-override")
        self.assertEqual(settings.openai_vision_model, "vision-override")


if __name__ == "__main__":
    unittest.main()
