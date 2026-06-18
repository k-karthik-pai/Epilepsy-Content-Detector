from __future__ import annotations

import unittest
import uuid

from epilepsy_guard.single_instance import SingleInstanceLock


class SingleInstanceTests(unittest.TestCase):
    def test_only_one_lock_can_hold_the_same_name(self) -> None:
        name = f"Local\\EpilepsyGuard.Test.{uuid.uuid4()}"
        first = SingleInstanceLock(name)
        second = SingleInstanceLock(name)
        try:
            self.assertTrue(first.acquired)
            self.assertFalse(second.acquired)
        finally:
            second.close()
            first.close()

        third = SingleInstanceLock(name)
        try:
            self.assertTrue(third.acquired)
        finally:
            third.close()


if __name__ == "__main__":
    unittest.main()
