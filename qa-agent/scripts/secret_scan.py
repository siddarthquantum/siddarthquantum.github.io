"""Pre-commit secret scan for the PUBLIC repo (sichakra.in). Run before every commit:

    .venv\\Scripts\\python.exe scripts\\secret_scan.py

Scans every file git would commit (tracked + staged + untracked-not-ignored) in the whole repo for:
  - the literal values of secret-looking variables in .env and profiles/client.env
    (names containing KEY, PASSWORD, SECRET, TOKEN, USERNAME, OTP, PIN),
  - Google API keys (AIza...), private keys, and local Windows user paths.
Prints file:line and the variable NAME or pattern only, never a secret value. Exit code 1 if anything is found.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # qa-agent/
SECRET_NAME = re.compile(r"KEY|PASSWORD|SECRET|TOKEN|USERNAME|OTP|PIN", re.I)
PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "local user path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+\w+", re.I),
}
PLACEHOLDER = re.compile(r"^(|paste.*|choose.*|<.*>|changeme|xxx+)$", re.I)


def secret_values() -> dict[str, str]:
    values = {}
    for env in (ROOT / ".env", ROOT / "profiles" / "client.env"):
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"').strip("'")
            if SECRET_NAME.search(name) and len(value) >= 4 and not PLACEHOLDER.match(value):
                values[f"{env.name}:{name}"] = value
    return values


def files_to_commit(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    return [repo / f for f in out.splitlines() if (repo / f).is_file()]


def main() -> int:
    repo = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip())
    secrets = secret_values()
    hits, scanned = [], 0
    for path in files_to_commit(repo):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary (png, apk): not scanned as text
        scanned += 1
        rel = path.relative_to(repo).as_posix()
        for no, line in enumerate(text.splitlines(), 1):
            for label, value in secrets.items():
                if value in line:
                    hits.append(f"{rel}:{no}  value of {label}")
            for label, rx in PATTERNS.items():
                if rx.search(line):
                    hits.append(f"{rel}:{no}  {label}")
    print(f"Secret scan: {scanned} text files, {len(secrets)} secret values from .env/client.env checked.")
    if hits:
        print("FOUND (fix before committing):")
        print("\n".join("  " + h for h in hits))
        return 1
    print("Clean: no secret values, API keys, private keys or local user paths found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
