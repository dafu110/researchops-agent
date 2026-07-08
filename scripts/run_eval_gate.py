import asyncio
import os
import sys
import tempfile
from pathlib import Path


def configure_environment() -> None:
    os.environ.setdefault("STORE_BACKEND", "json")
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="researchops-eval-"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    configure_environment()

    from app.core.security import UserContext
    from app.evals.service import eval_service

    result = await eval_service.run_golden(
        UserContext(user_id="eval-runner", tenant_id="eval", role="admin")
    )
    print(f"pass_rate={result.pass_rate}")
    print(f"citation_correctness={result.citation_correctness}")
    for item in result.results:
        print(
            f"{item.case_id}: passed={item.passed} "
            f"missing={item.missing_terms} citation={item.citation_correct}"
        )
    if result.pass_rate < 0.8 or result.citation_correctness < 0.8:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
