"""Guard the one exception for VK ORM production formatting drift."""
import unittest

from scripts.deploy_servgo_frontend_atomic import backend_equivalent


class VkFrontendAstGateTests(unittest.TestCase):
    def test_accepts_whitespace_and_comments_only_for_orm(self):
        original = b"from typing import Optional\nclass Example:\n    field: Optional[int] = 1\n"
        formatted = b"# production comment\nfrom typing import Optional\n\nclass Example:\n    field: Optional[int] = 1  # comment\n"
        self.assertTrue(backend_equivalent("database/models.py", formatted, original))
        self.assertFalse(backend_equivalent("database/account_link.py", formatted, original))

    def test_rejects_any_orm_semantic_change(self):
        source = b"class Example:\n    field = 1\n"
        changed = b"class Example:\n    field = 2\n"
        self.assertFalse(backend_equivalent("database/models.py", changed, source))

    def test_rejects_invalid_orm_source(self):
        self.assertFalse(backend_equivalent("database/models.py", b"class Broken(\n", b"class Good: pass\n"))

    def test_exact_bytes_remain_accepted(self):
        source = b"class Example: pass\n"
        self.assertTrue(backend_equivalent("database/models.py", source, source))


if __name__ == "__main__":
    unittest.main()
