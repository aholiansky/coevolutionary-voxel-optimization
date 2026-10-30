import unittest

from mcstego.worldgen.generator import (
    _line_reports_chunky_completion,
    _stalled_chunk_flush_due,
)


class WorldgenGeneratorTests(unittest.TestCase):
    def test_chunky_completion_accepts_dot_and_comma_decimal_formats(self) -> None:
        self.assertTrue(
            _line_reports_chunky_completion(
                "Task finished: 1024 chunks (100.00%), Total time: 0:00:17"
            )
        )
        self.assertTrue(
            _line_reports_chunky_completion(
                "Task finished: 1024 chunks (100,00%), Total time: 0:00:17"
            )
        )
        self.assertFalse(
            _line_reports_chunky_completion(
                "Task running: 1020 chunks (99.61%), Total time: 0:00:16"
            )
        )

    def test_stalled_near_complete_generation_requests_a_flush(self) -> None:
        self.assertTrue(
            _stalled_chunk_flush_due(
                present_chunks=1020,
                expected_chunks=1024,
                now=20.0,
                last_progress_at=5.0,
                last_flush_at=None,
            )
        )

    def test_flush_waits_for_stall_threshold_and_cooldown(self) -> None:
        common = {
            "expected_chunks": 1024,
            "now": 20.0,
        }
        self.assertFalse(
            _stalled_chunk_flush_due(
                present_chunks=1000,
                last_progress_at=5.0,
                last_flush_at=None,
                **common,
            )
        )
        self.assertFalse(
            _stalled_chunk_flush_due(
                present_chunks=1020,
                last_progress_at=15.0,
                last_flush_at=None,
                **common,
            )
        )
        self.assertFalse(
            _stalled_chunk_flush_due(
                present_chunks=1020,
                last_progress_at=5.0,
                last_flush_at=15.0,
                **common,
            )
        )


if __name__ == "__main__":
    unittest.main()
