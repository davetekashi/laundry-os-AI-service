import unittest
from uuid import uuid4

from app.schemas.context import ContextRole, ContextSnapshot
from app.services.context_cache import get_context, restore_context, snapshot_scope_key
from app.services.conversation_cache import (
    append_exchange,
    get_conversation,
    load_conversation,
    restore_conversation,
)


class RuntimeStateTests(unittest.TestCase):
    def test_context_snapshot_can_be_restored_after_serialization(self):
        laundry_id = str(uuid4())
        snapshot = ContextSnapshot(
            laundry_id=laundry_id,
            role=ContextRole.OWNER,
            prepared_at="2026-10-30T12:00:00+00:00",
            context={"orders": {"total_orders": 3}},
            retrieval_data={"orders": [{"order_id": "order-1"}]},
        )

        restored = restore_context(snapshot.model_dump(mode="json"))

        self.assertEqual(snapshot_scope_key(restored), f"laundry:{laundry_id}")
        self.assertEqual(
            get_context(laundry_id, ContextRole.OWNER),
            snapshot,
        )

    def test_conversation_can_be_exported_and_restored(self):
        scope_key = f"laundry:{uuid4()}"
        conversation_id, _ = load_conversation(None, scope_key, ContextRole.OWNER)
        append_exchange(conversation_id, "How are we doing?", "Orders are growing.")
        exported = get_conversation(conversation_id)
        self.assertIsNotNone(exported)

        restored = restore_conversation(
            {
                "conversation_id": exported.conversation_id,
                "scope_key": exported.scope_key,
                "role": exported.role.value,
                "messages": exported.messages,
            }
        )

        self.assertEqual(restored.scope_key, scope_key)
        self.assertEqual(len(restored.messages), 2)
        self.assertEqual(restored.messages[-1]["content"], "Orders are growing.")


if __name__ == "__main__":
    unittest.main()
