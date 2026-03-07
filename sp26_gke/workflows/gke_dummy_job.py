"""
Dummy GKE workflow job.

Students can replace this module with real agent logic while keeping the same container
+ Kubernetes deployment plumbing.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _log(event: str, **fields: object) -> None:
    payload = {"ts": _now_iso(), "event": event, **fields}
    print(json.dumps(payload), flush=True)


def run() -> int:
    run_id = str(uuid.uuid4())
    loop_count = int(os.getenv("DUMMY_LOOP_COUNT", "5"))
    sleep_seconds = float(os.getenv("DUMMY_SLEEP_SECONDS", "3"))
    fail_on_purpose = os.getenv("DUMMY_FAIL", "false").lower() == "true"

    _log(
        "dummy_job_started",
        run_id=run_id,
        loop_count=loop_count,
        sleep_seconds=sleep_seconds,
    )

    for step in range(1, loop_count + 1):
        _log("dummy_job_step", run_id=run_id, step=step, total=loop_count)
        time.sleep(sleep_seconds)

    if fail_on_purpose:
        _log("dummy_job_failed", run_id=run_id, reason="DUMMY_FAIL=true")
        return 1

    _log("dummy_job_completed", run_id=run_id)
    return 0


if __name__ == "__main__":
    sys.exit(run())
