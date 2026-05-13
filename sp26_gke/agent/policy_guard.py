"""PolicyGuard: action-level policy enforcement and append-only audit logging."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sp26_gke.agent.orchestrator import FixResult, HistoryEntry, ReviewResult

# Phrases that suggest prompt injection is attempting to steer the orchestrator.
# Checked in both the LLM's stated reason and in the raw input code.
_INJECTION_PATTERNS: list[str] = [
    "system override",
    "orchestrator note",
    "orchestrator instruction",
    "action: accept",
    "action: give_up",
    "pre-verified",
    "external audit",
    "skip all sub-agents",
    "skip sub-agents",
    "audit log",
    "confirmed correct",
]

_DEFAULT_AUDIT_PATH = Path("/workspace/audit.jsonl")


@dataclass
class PolicyDecision:
    allowed: bool
    rule: str  # human-readable name of the rule that fired
    action: str  # proposed action
    reason: str  # LLM's stated reason
    step: int


class PolicyGuard:
    """Enforces structural action policies and writes an append-only audit log."""

    def __init__(self, audit_log_path: Path = _DEFAULT_AUDIT_PATH) -> None:
        self._audit = audit_log_path
        # Ensure the parent directory exists (best-effort; audit must not crash agent)
        try:
            self._audit.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_code(self, code: str) -> PolicyDecision:
        """Scan input code for embedded orchestrator directives before the loop
        starts."""
        code_lower = code.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in code_lower:
                decision = PolicyDecision(
                    allowed=False,
                    rule="injection_pattern_in_code",
                    action="(pre-loop code scan)",
                    reason=f"Input code contains suspicious pattern: '{pattern}'",
                    step=0,
                )
                self._log(decision)
                return decision
        decision = PolicyDecision(
            allowed=True,
            rule="code_scan_clean",
            action="(pre-loop code scan)",
            reason="No injection patterns found in input code.",
            step=0,
        )
        self._log(decision)
        return decision

    def check(
        self,
        action: str,
        reason: str,
        step: int,
        history: list[HistoryEntry],
    ) -> PolicyDecision:
        """Evaluate a proposed action; log and return the decision."""
        decision = self._evaluate(action, reason, step, history)
        self._log(decision)
        return decision

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        action: str,
        reason: str,
        step: int,
        history: list[HistoryEntry],
    ) -> PolicyDecision:
        def deny(rule: str) -> PolicyDecision:
            return PolicyDecision(
                allowed=False, rule=rule, action=action, reason=reason, step=step
            )

        def allow() -> PolicyDecision:
            return PolicyDecision(
                allowed=True,
                rule="all_checks_passed",
                action=action,
                reason=reason,
                step=step,
            )

        # Rule 1 — injection patterns in the LLM's stated reason
        reason_lower = reason.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in reason_lower:
                return deny("injection_pattern_in_reason")

        # Rule 2 — fix requires a prior diagnosis in history
        if action == "fix":
            if not any(e.action == "diagnose" for e in history):
                return deny("fix_requires_prior_diagnosis")

        # Rule 3 — review requires a prior fix in history
        if action == "review":
            if not any(e.action == "fix" for e in history):
                return deny("review_requires_prior_fix")

        # Rule 4 — accept requires the latest review to be approved
        if action == "accept":
            latest_review: ReviewResult | None = next(
                (
                    e.result
                    for e in reversed(history)
                    if e.action == "review" and isinstance(e.result, ReviewResult)
                ),
                None,
            )
            if latest_review is None or not latest_review.approved:
                return deny("accept_requires_approved_review")

        # Rule 5 — accept requires both the fixer and reviewer sandboxes to have passed
        if action == "accept":
            latest_fix: FixResult | None = next(
                (
                    e.result
                    for e in reversed(history)
                    if e.action == "fix" and isinstance(e.result, FixResult)
                ),
                None,
            )
            latest_review = next(
                (
                    e.result
                    for e in reversed(history)
                    if e.action == "review" and isinstance(e.result, ReviewResult)
                ),
                None,
            )
            if latest_fix is None or not latest_fix.sandbox_passed:
                return deny("accept_requires_fixer_sandbox_pass")
            if latest_review is None or not latest_review.reviewer_passed:
                return deny("accept_requires_reviewer_sandbox_pass")

        return allow()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def _log(self, decision: PolicyDecision) -> None:
        entry = {
            "timestamp": time.time(),
            "step": decision.step,
            "action": decision.action,
            "allowed": decision.allowed,
            "rule": decision.rule,
            "reason": decision.reason[:300],
        }
        verdict = "ALLOW" if decision.allowed else "DENY"
        print(
            f"[PolicyGuard] {verdict} | step={decision.step} action={decision.action} rule={decision.rule}"
        )
        try:
            with self._audit.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # audit failure must never crash the agent
