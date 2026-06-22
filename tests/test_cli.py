"""Tests for ai_digest.cli — the unified main() entry point.

Covers:
- --run-once flag
- RUN_ONCE=true env var
- daemon / scheduler path
- shim identity: digest.main is cli.main, __main__.main is cli.main
- startup notification failure is swallowed
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from ai_digest.cli import main


class TestCliRunOnce(unittest.TestCase):
    """--run-once and RUN_ONCE=true must trigger a single digest run and return."""

    def _run_once_via_flag(self, patch_svc):
        with (
            patch("ai_digest.cli.run_digest_service", patch_svc),
            patch("sys.argv", ["ai-digest", "--run-once"]),
        ):
            main()

    def _run_once_via_env(self, patch_svc):
        with (
            patch("ai_digest.cli.run_digest_service", patch_svc),
            patch.dict("os.environ", {"RUN_ONCE": "true"}),
            patch("sys.argv", ["ai-digest"]),
        ):
            main()

    def test_run_once_flag_calls_service_exactly_once(self):
        mock_svc = Mock()
        self._run_once_via_flag(mock_svc)
        mock_svc.assert_called_once()

    def test_run_once_env_var_calls_service_exactly_once(self):
        mock_svc = Mock()
        self._run_once_via_env(mock_svc)
        mock_svc.assert_called_once()

    def test_run_once_passes_config_to_service(self):
        """run_digest_service must receive the AppConfig built from env."""
        from ai_digest.config import AppConfig

        captured: list = []

        def capture(cfg):
            captured.append(cfg)

        with (
            patch("ai_digest.cli.run_digest_service", capture),
            patch("sys.argv", ["ai-digest", "--run-once"]),
        ):
            main()

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], AppConfig)

    def test_run_once_does_not_enter_scheduler(self):
        """--run-once must never call schedule.every."""
        with (
            patch("ai_digest.cli.run_digest_service"),
            patch("ai_digest.cli.schedule") as mock_sched,
            patch("sys.argv", ["ai-digest", "--run-once"]),
        ):
            main()

        mock_sched.every.assert_not_called()

    def test_run_once_env_false_not_treated_as_run_once(self):
        """RUN_ONCE=false must not trigger one-shot mode."""
        mock_svc = Mock()
        with (
            patch("ai_digest.cli.run_digest_service", mock_svc),
            patch("ai_digest.cli.schedule"),
            patch("ai_digest.cli.time.sleep", side_effect=KeyboardInterrupt),
            patch("ai_digest.cli.send_telegram"),
            patch.dict("os.environ", {"RUN_ONCE": "false"}),
            patch("sys.argv", ["ai-digest"]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                main()

        # In daemon mode run_digest_service is NOT called at startup
        mock_svc.assert_not_called()


class TestCliDaemonMode(unittest.TestCase):
    """Scheduler / daemon path: sets up daily job, loops until interrupted."""

    def _daemon_until_interrupt(self, extra_patches=None):
        patches = {
            "ai_digest.cli.send_telegram": Mock(),
            "ai_digest.cli.schedule": MagicMock(),
            "ai_digest.cli.time.sleep": Mock(side_effect=KeyboardInterrupt),
        }
        if extra_patches:
            patches.update(extra_patches)
        stack = [patch(k, v) for k, v in patches.items()]
        mocks = {}
        for p in stack:
            m = p.start()
            mocks[p.attribute] = m
        try:
            with self.assertRaises(KeyboardInterrupt):
                with patch("sys.argv", ["ai-digest"]):
                    main()
        finally:
            for p in stack:
                p.stop()
        return mocks

    def test_scheduler_registers_daily_job(self):
        with (
            patch("ai_digest.cli.send_telegram"),
            patch("ai_digest.cli.schedule") as mock_sched,
            patch("ai_digest.cli.time.sleep", side_effect=KeyboardInterrupt),
            patch("sys.argv", ["ai-digest"]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                main()

        mock_sched.every.assert_called()

    def test_scheduler_job_uses_run_digest_service(self):
        """The job registered with schedule must be run_digest_service."""
        from ai_digest.digest.service import run_digest_service

        registered_fn: list = []

        def capture_do(fn, *args, **kwargs):
            registered_fn.append(fn)

        mock_sched = MagicMock()
        mock_sched.every.return_value.day.at.return_value.do.side_effect = capture_do

        with (
            patch("ai_digest.cli.send_telegram"),
            patch("ai_digest.cli.schedule", mock_sched),
            patch("ai_digest.cli.time.sleep", side_effect=KeyboardInterrupt),
            patch("sys.argv", ["ai-digest"]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                main()

        self.assertEqual(len(registered_fn), 1)
        self.assertIs(registered_fn[0], run_digest_service)

    def test_startup_notification_failure_is_swallowed(self):
        """If send_telegram raises on startup, main() must continue without raising."""
        with (
            patch("ai_digest.cli.send_telegram", side_effect=RuntimeError("network")),
            patch("ai_digest.cli.schedule"),
            patch("ai_digest.cli.time.sleep", side_effect=KeyboardInterrupt),
            patch("sys.argv", ["ai-digest"]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                main()  # must not raise RuntimeError


class TestCliShimIdentity(unittest.TestCase):
    """All entry points must reference the same main() function."""

    def test_digest_main_is_cli_main(self):
        import digest
        from ai_digest.cli import main as cli_main

        self.assertIs(digest.main, cli_main)

    def test_dunder_main_is_cli_main(self):
        import ai_digest.__main__ as m
        from ai_digest.cli import main as cli_main

        self.assertIs(m.main, cli_main)

    def test_pyproject_scripts_target_exists(self):
        """Verify the module path referenced in [project.scripts] is importable."""
        from ai_digest.cli import main  # noqa: F401

        self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main()
