"""
Unit tests for the LLM-driven dynamic orchestrator.

All Kubernetes and LLM calls are mocked so the tests run locally without any
infrastructure.
"""

from unittest.mock import MagicMock, patch

import pytest
from sp26_gke.agent.orchestrator import (
    DiagnoseResult,
    FixResult,
    HistoryEntry,
    ReviewResult,
    _build_failure_context,
    _next_action,
    run_orchestrator,
)


def _make_llm_response(text: str) -> MagicMock:
    r = MagicMock()
    r.content = text
    return r


def _diag(step: int, diagnosis: str) -> HistoryEntry:
    return HistoryEntry(step=step, action="diagnose", result=DiagnoseResult(diagnosis))


def _fix(
    step: int, passed: bool, code: str = "def add(a,b): return a+b"
) -> HistoryEntry:
    result = "PASSED" if passed else "AssertionError: expected 5 got 4"
    return HistoryEntry(step=step, action="fix", result=FixResult(code, result, passed))


def _review(step: int, approved: bool, passed: bool) -> HistoryEntry:
    decision = "APPROVED looks good" if approved else "REJECTED tests still fail"
    return HistoryEntry(
        step=step, action="review", result=ReviewResult(decision, passed, approved)
    )


class TestBuildFailureContext:
    def test_returns_none_with_empty_history(self):
        assert _build_failure_context([]) is None

    def test_returns_none_with_only_diagnose(self):
        assert _build_failure_context([_diag(1, "wrong op")]) is None

    def test_includes_diagnosis_and_fix_failure(self):
        history = [_diag(1, "wrong operator"), _fix(2, passed=False)]
        ctx = _build_failure_context(history)
        assert ctx is not None
        assert "wrong operator" in ctx
        assert "FAILED" in ctx

    def test_includes_review_rejection(self):
        history = [
            _diag(1, "wrong op"),
            _fix(2, passed=True),
            _review(3, approved=False, passed=False),
        ]
        ctx = _build_failure_context(history)
        assert ctx is not None
        assert "REJECTED" in ctx

    def test_multiple_attempts_all_included(self):
        history = [
            _diag(1, "first diagnosis"),
            _fix(2, passed=False),
            _diag(3, "second diagnosis"),
            _fix(4, passed=True),
            _review(5, approved=False, passed=False),
        ]
        ctx = _build_failure_context(history)
        assert ctx is not None
        assert "first diagnosis" in ctx
        assert "second diagnosis" in ctx


class TestNextAction:
    def _llm(self, text: str) -> MagicMock:
        m = MagicMock()
        m.invoke.return_value = _make_llm_response(text)
        return m

    def test_parses_diagnose(self):
        action, reason = _next_action(
            self._llm("ACTION: diagnose\nREASON: need to identify the bug"),
            "code",
            [],
            5,
        )
        assert action == "diagnose"
        assert "identify" in reason

    def test_parses_fix(self):
        action, _ = _next_action(
            self._llm("ACTION: fix\nREASON: apply the diagnosis"), "code", [], 5
        )
        assert action == "fix"

    def test_parses_review(self):
        action, _ = _next_action(
            self._llm("ACTION: review\nREASON: verify fix"), "code", [], 5
        )
        assert action == "review"

    def test_parses_accept(self):
        action, _ = _next_action(
            self._llm("ACTION: accept\nREASON: all passed"), "code", [], 5
        )
        assert action == "accept"

    def test_parses_give_up(self):
        action, _ = _next_action(
            self._llm("ACTION: give_up\nREASON: hopeless"), "code", [], 5
        )
        assert action == "give_up"

    def test_invalid_action_defaults_to_give_up(self):
        action, _ = _next_action(
            self._llm("ACTION: explode\nREASON: chaos"), "code", [], 5
        )
        assert action == "give_up"

    def test_history_appears_in_prompt(self):
        llm = self._llm("ACTION: give_up\nREASON: no progress")
        history = [_diag(1, "wrong subtraction operator")]
        _next_action(llm, "buggy code", history, 5)
        prompt = llm.invoke.call_args[0][0]
        assert "wrong subtraction operator" in prompt
        assert "buggy code" in prompt

    def test_steps_remaining_in_prompt(self):
        llm = self._llm("ACTION: give_up\nREASON: done")
        _next_action(llm, "code", [], 3)
        prompt = llm.invoke.call_args[0][0]
        assert "3" in prompt


class TestRunOrchestrator:
    @pytest.fixture()
    def _patch_k8s(self):
        with patch("sp26_gke.agent.orchestrator.config") as mock_cfg:
            mock_cfg.load_kube_config.return_value = None
            yield

    def _run(
        self, actions: list[tuple[str, str]], diagnoser=None, fixer=None, reviewer=None
    ):
        """Helper: patches everything and runs the orchestrator."""

        def diagnoser_fn(code, failure_context=None):
            return DiagnoseResult("wrong operator")

        def fixer_fn(code, diagnosis):
            return FixResult("def add(a,b): return a+b", "PASSED", True)

        def reviewer_fn(original, fixed, fixer_result):
            return ReviewResult("APPROVED looks good", True, True)

        llm = MagicMock()
        llm.invoke.side_effect = [
            _make_llm_response(f"ACTION: {a}\nREASON: {r}") for a, r in actions
        ]

        with (
            patch(
                "sp26_gke.agent.orchestrator._run_diagnoser",
                side_effect=diagnoser or diagnoser_fn,
            ),
            patch(
                "sp26_gke.agent.orchestrator._run_fixer", side_effect=fixer or fixer_fn
            ),
            patch(
                "sp26_gke.agent.orchestrator._run_reviewer",
                side_effect=reviewer or reviewer_fn,
            ),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch(
                "sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI", return_value=llm
            ),
        ):
            mock_path.return_value.read_text.return_value = "def add(a,b): return a-b"
            run_orchestrator()

    def test_happy_path_passes(self, _patch_k8s, capsys):
        self._run(
            [
                ("diagnose", "find bug"),
                ("fix", "apply fix"),
                ("review", "verify"),
                ("accept", "done"),
            ]
        )
        assert "AGENT STATUS: PASSED" in capsys.readouterr().out

    def test_give_up_emits_failed(self, _patch_k8s, capsys):
        self._run(
            [
                ("diagnose", "find bug"),
                ("fix", "apply"),
                ("review", "check"),
                ("give_up", "hopeless"),
            ]
        )
        assert "AGENT STATUS: FAILED" in capsys.readouterr().out

    def test_llm_can_diagnose_twice_before_fixing(self, _patch_k8s, capsys):
        diagnosed: list[str | None] = []

        def diagnoser(code, failure_context=None):
            diagnosed.append(failure_context)
            return DiagnoseResult("wrong operator")

        self._run(
            [
                ("diagnose", "first pass"),
                ("diagnose", "second pass"),
                ("fix", "now fix"),
                ("review", "verify"),
                ("accept", "done"),
            ],
            diagnoser=diagnoser,
        )
        assert len(diagnosed) == 2
        assert "AGENT STATUS: PASSED" in capsys.readouterr().out

    def test_second_diagnose_receives_failure_context(self, _patch_k8s):
        diagnosed_contexts: list[str | None] = []

        def diagnoser(code, failure_context=None):
            diagnosed_contexts.append(failure_context)
            return DiagnoseResult("wrong operator")

        attempt = {"n": 0}

        def fixer(code, diagnosis):
            attempt["n"] += 1
            passed = attempt["n"] > 1
            return FixResult(
                "def add(a,b): return a+b",
                "PASSED" if passed else "AssertionError",
                passed,
            )

        def reviewer(original, fixed, fixer_result):
            passed = attempt["n"] > 1
            decision = "APPROVED" if passed else "REJECTED"
            return ReviewResult(decision, passed, passed)

        self._run(
            [
                ("diagnose", "first"),
                ("fix", "fix1"),
                ("review", "rev1"),
                ("diagnose", "second — diff approach"),
                ("fix", "fix2"),
                ("review", "rev2"),
                ("accept", "done"),
            ],
            diagnoser=diagnoser,
            fixer=fixer,
            reviewer=reviewer,
        )
        # First call: no prior failures, context is None
        assert diagnosed_contexts[0] is None
        # Second call: has failure history, context is not None
        assert diagnosed_contexts[1] is not None

    def test_max_steps_ceiling_stops_loop(self, _patch_k8s, capsys):
        # Feed more actions than _MAX_STEPS — loop must stop at ceiling
        many_diagnoses = [("diagnose", f"step {i}") for i in range(20)]
        self._run(many_diagnoses)
        assert "AGENT STATUS: FAILED" in capsys.readouterr().out

    def test_fix_without_diagnosis_stops(self, _patch_k8s, capsys):
        self._run([("fix", "skip diagnosis — should stop")])
        assert "AGENT STATUS: FAILED" in capsys.readouterr().out

    def test_review_without_fix_stops(self, _patch_k8s, capsys):
        self._run([("review", "skip fix — should stop")])
        assert "AGENT STATUS: FAILED" in capsys.readouterr().out

    def test_history_grows_across_steps(self, _patch_k8s):
        history_sizes: list[int] = []

        def capturing_next_action(llm, code, history, remaining):
            history_sizes.append(len(history))
            actions = [
                ("diagnose", "a"),
                ("fix", "b"),
                ("review", "c"),
                ("accept", "d"),
            ]
            idx = len(history_sizes) - 1
            a, r = actions[idx] if idx < len(actions) else ("give_up", "done")
            return a, r

        with (
            patch(
                "sp26_gke.agent.orchestrator._run_diagnoser",
                return_value=DiagnoseResult("d"),
            ),
            patch(
                "sp26_gke.agent.orchestrator._run_fixer",
                return_value=FixResult("code", "PASSED", True),
            ),
            patch(
                "sp26_gke.agent.orchestrator._run_reviewer",
                return_value=ReviewResult("APPROVED", True, True),
            ),
            patch(
                "sp26_gke.agent.orchestrator._next_action",
                side_effect=capturing_next_action,
            ),
            patch("sp26_gke.agent.orchestrator.Path") as mock_path,
            patch("sp26_gke.agent.orchestrator.ChatGoogleGenerativeAI"),
            patch("sp26_gke.agent.orchestrator.config"),
        ):
            mock_path.return_value.read_text.return_value = "buggy"
            run_orchestrator()

        # Each step the LLM sees one more history entry than the previous step
        assert history_sizes == [0, 1, 2, 3]
