"""
Unit tests for the LLM-driven orchestrator.

All Kubernetes and LLM calls are mocked so the tests run locally without any
infrastructure.
"""

from unittest.mock import MagicMock, patch

import pytest
from sp26_gke.agent.orchestrator import _decide_next_action, run_orchestrator


def _make_llm_response(text: str) -> MagicMock:
    r = MagicMock()
    r.content = text
    return r


class TestDecideNextAction:
    """Tests for the LLM-driven action decision function."""

    def _llm(self, response_text: str) -> MagicMock:
        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response(response_text)
        return llm

    def test_returns_accept_when_llm_says_accept(self):
        llm = self._llm("ACTION: ACCEPT\nHINT: none")
        action, hint = _decide_next_action(
            llm,
            attempt=1,
            max_attempts=3,
            fixer_sandbox_passed=True,
            reviewer_sandbox_passed=True,
            review_decision="APPROVED looks good",
            diagnosis="wrong operator",
            fixer_sandbox_result="All tests passed",
        )
        assert action == "ACCEPT"
        assert hint == ""

    def test_returns_retry_with_hint(self):
        llm = self._llm(
            "ACTION: RETRY\nHINT: The off-by-one was in the loop bound, not the operator."
        )
        action, hint = _decide_next_action(
            llm,
            attempt=1,
            max_attempts=3,
            fixer_sandbox_passed=False,
            reviewer_sandbox_passed=False,
            review_decision="REJECTED tests still fail",
            diagnosis="wrong operator",
            fixer_sandbox_result="AssertionError: expected 5 got 4",
        )
        assert action == "RETRY"
        assert "off-by-one" in hint

    def test_returns_give_up(self):
        llm = self._llm("ACTION: GIVE_UP\nHINT: none")
        action, hint = _decide_next_action(
            llm,
            attempt=2,
            max_attempts=3,
            fixer_sandbox_passed=False,
            reviewer_sandbox_passed=False,
            review_decision="REJECTED",
            diagnosis="some diagnosis",
            fixer_sandbox_result="Traceback ...",
        )
        assert action == "GIVE_UP"
        assert hint == ""

    def test_unknown_action_defaults_to_give_up(self):
        llm = self._llm("ACTION: SOMETHING_WEIRD\nHINT: none")
        action, _ = _decide_next_action(
            llm,
            attempt=1,
            max_attempts=3,
            fixer_sandbox_passed=False,
            reviewer_sandbox_passed=False,
            review_decision="REJECTED",
            diagnosis="d",
            fixer_sandbox_result="",
        )
        assert action == "GIVE_UP"

    def test_hint_is_empty_when_none(self):
        llm = self._llm("ACTION: RETRY\nHINT: none")
        _, hint = _decide_next_action(llm, 1, 3, False, False, "REJECTED", "d", "")
        assert hint == ""

    def test_llm_receives_attempt_context(self):
        llm = self._llm("ACTION: GIVE_UP\nHINT: none")
        _decide_next_action(
            llm, 2, 3, False, True, "REJECTED bad fix", "wrong op", "AssertionError"
        )
        prompt = llm.invoke.call_args[0][0]
        assert "Attempt 2 of 3" in prompt
        assert "FAILED" in prompt  # fixer sandbox failed
        assert "PASSED" in prompt  # reviewer sandbox passed
        assert "wrong op" in prompt


class TestRunOrchestrator:
    """Integration-style tests for run_orchestrator, with K8s and LLM mocked."""

    @pytest.fixture()
    def _patch_k8s(self):
        with patch("sp26_gke.agent.orchestrator.config") as mock_cfg:
            mock_cfg.load_kube_config.return_value = None
            yield mock_cfg

    def _make_runner(
        self,
        diagnoser_diagnosis: str = "wrong operator",
        fixed_code: str = "def add(a, b):\n    return a + b\n",
        fixer_sandbox_result: str = "PASSED",
        review_decision: str = "APPROVED looks good",
        reviewer_sandbox_passed: bool = True,
    ):
        """Return patched versions of _run_diagnoser, _run_fixer, _run_reviewer."""

        def diagnoser(code, failure_context=None):
            return diagnoser_diagnosis

        def fixer(code, diagnosis):
            return fixed_code, fixer_sandbox_result

        def reviewer(original, fixed, fixer_result):
            return review_decision, reviewer_sandbox_passed

        return diagnoser, fixer, reviewer

    def test_succeeds_on_first_attempt(self, _patch_k8s, capsys):
        diagnoser, fixer, reviewer = self._make_runner()

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch("sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI"),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

        out = capsys.readouterr().out
        assert "AGENT STATUS: PASSED" in out
        assert "FINAL CODE START" in out

    def test_retries_with_failure_context_on_second_attempt(self, _patch_k8s, capsys):
        calls: list[str | None] = []

        def diagnoser(code, failure_context=None):
            calls.append(failure_context)
            return "wrong operator"

        attempt = {"n": 0}

        def fixer(code, diagnosis):
            attempt["n"] += 1
            if attempt["n"] == 1:
                return "def add(a,b): return a-b", "AssertionError"
            return "def add(a,b): return a+b", "PASSED"

        def reviewer(original, fixed, fixer_result):
            if attempt["n"] == 1:
                return "REJECTED tests still fail", False
            return "APPROVED", True

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response(
            "ACTION: RETRY\nHINT: The subtraction operator should be addition."
        )

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI",
                return_value=llm,
            ),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

        out = capsys.readouterr().out
        assert "AGENT STATUS: PASSED" in out
        # First diagnoser call has no context; second has failure context
        assert calls[0] is None
        assert calls[1] is not None
        assert "subtraction" in calls[1]

    def test_give_up_stops_before_max_attempts(self, _patch_k8s, capsys):
        diagnoser_call_count = {"n": 0}

        def diagnoser(code, failure_context=None):
            diagnoser_call_count["n"] += 1
            return "wrong operator"

        def fixer(code, diagnosis):
            return "def add(a,b): return a-b", "AssertionError"

        def reviewer(original, fixed, fixer_result):
            return "REJECTED fundamentally broken", False

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response("ACTION: GIVE_UP\nHINT: none")

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI",
                return_value=llm,
            ),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

        out = capsys.readouterr().out
        assert "AGENT STATUS: FAILED" in out
        # LLM said give up after attempt 1, so only 1 diagnoser call
        assert diagnoser_call_count["n"] == 1

    def test_fails_after_max_attempts_exhausted(self, _patch_k8s, capsys):
        diagnoser_call_count = {"n": 0}

        def diagnoser(code, failure_context=None):
            diagnoser_call_count["n"] += 1
            return "wrong operator"

        def fixer(code, diagnosis):
            return "def add(a,b): return a-b", "AssertionError"

        def reviewer(original, fixed, fixer_result):
            return "REJECTED still failing", False

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response(
            "ACTION: RETRY\nHINT: try something else"
        )

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI",
                return_value=llm,
            ),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

        out = capsys.readouterr().out
        assert "AGENT STATUS: FAILED" in out
        assert diagnoser_call_count["n"] == 3  # all 3 attempts ran

    def test_empty_fixer_output_does_not_call_reviewer(self, _patch_k8s, capsys):
        reviewer_called = {"n": 0}

        def diagnoser(code, failure_context=None):
            return "wrong operator"

        def fixer(code, diagnosis):
            return "", ""  # empty output

        def reviewer(original, fixed, fixer_result):
            reviewer_called["n"] += 1
            return "APPROVED", True

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response("ACTION: GIVE_UP\nHINT: none")

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI",
                return_value=llm,
            ),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

        assert reviewer_called["n"] == 0

    def test_always_diagnoses_original_code_not_previous_fix(self, _patch_k8s):
        diagnosed_codes: list[str] = []
        original = "def add(a,b): return a-b"

        def diagnoser(code, failure_context=None):
            diagnosed_codes.append(code)
            return "wrong operator"

        attempt = {"n": 0}

        def fixer(code, diagnosis):
            attempt["n"] += 1
            if attempt["n"] == 1:
                return "def add(a,b): return a*b", "AssertionError"
            return "def add(a,b): return a+b", "PASSED"

        def reviewer(original, fixed, fixer_result):
            if attempt["n"] == 1:
                return "REJECTED", False
            return "APPROVED", True

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response(
            "ACTION: RETRY\nHINT: wrong fix applied"
        )

        with (
            patch("sp26_gke.agent.orchestrator._run_diagnoser", side_effect=diagnoser),
            patch("sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer),
            patch("sp26_gke.agent.orchestrator._run_reviewer", side_effect=reviewer),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI",
                return_value=llm,
            ),
        ):
            mock_path.return_value.read_text.return_value = original
            run_orchestrator()

        # Both diagnoser calls must receive the original code, not the failed fix
        assert all(c == original for c in diagnosed_codes)
