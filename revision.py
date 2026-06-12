import os
import subprocess


_REVISION_ENV_VARS = (
    "STREAMLIT_GIT_COMMIT",
    "GITHUB_SHA",
    "COMMIT_SHA",
    "SOURCE_VERSION",
)


def get_deployment_revision() -> str:
    """Return the deployed commit SHA when available."""
    for name in _REVISION_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value[:12]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"

    return result.stdout.strip() or "unknown"
