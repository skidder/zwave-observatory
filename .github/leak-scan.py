#!/usr/bin/env python3
"""Leak scan: blocks publishing if repo text files contain private data.

Checks for:
  - RFC1918 private IPv4 addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
  - Home-ID-like 10-digit numbers (Z-Wave home IDs are 10 hex-ish digits;
    a 10-digit decimal run is a common accidental paste)
  - Forbidden strings (real device names, hostnames, node ids) listed in
    FORBIDDEN below. Only synthetic names (Hallway Lights, Garage Door
    Sensor, Workbench Outlet, Media Center, Desk Lamp, Garage Interior
    Door) and sample node ids (11, 12, 13, 24, 32, 45, 46, 51-56) are
    allowed in docs and examples.

Exit code 0 = clean, 1 = leak found. Run as a CI step before publishing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Real device names, real hostnames, or real node ids that must never
# appear anywhere in this repository. Extend this list as needed.
FORBIDDEN = [
    # Add real device names here if they are ever committed by mistake.
]

# Text file extensions that are scanned.
SCANNED_EXTENSIONS = {
    ".md", ".txt", ".yml", ".yaml", ".json", ".py", ".sh", ".toml",
    ".cfg", ".ini", ".env", ".example", ".ts", ".tsx", ".js", ".jsx",
    ".css", ".html", ".sql", ".dockerfile",
}
SCANNED_FILENAMES = {
    "Dockerfile", "docker-compose.yml", ".env.example", ".gitignore",
    ".dockerignore", "LICENSE", "docker-entrypoint.sh",
}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "data",
             "dist", "build", ".pytest_cache", ".tsbuildinfo"}

PRIVATE_IP_RE = re.compile(
    r"\b(192\.168|10\.|172\.(1[6-9]|2[0-9]|3[01]))\.\d{1,3}\.\d{1,3}\b"
)
HOME_ID_RE = re.compile(r"\b\d{10}\b")


def iter_files():
    for path in REPO_ROOT.rglob("*"):
        if path.is_dir():
            if path.name in SKIP_DIRS:
                # Prune: rglob keeps descending, so filter later too.
                continue
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SCANNED_FILENAMES or path.suffix in SCANNED_EXTENSIONS:
            yield path


def scan():
    findings = []
    for path in sorted(iter_files()):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in PRIVATE_IP_RE.finditer(line):
                findings.append(f"{rel}:{lineno}: private IP {match.group(0)!r}")
            for match in HOME_ID_RE.finditer(line):
                findings.append(f"{rel}:{lineno}: 10-digit home-id-like number {match.group(0)!r}")
            for needle in FORBIDDEN:
                if needle and needle in line:
                    findings.append(f"{rel}:{lineno}: forbidden string {needle!r}")
    return findings


def main():
    findings = scan()
    if findings:
        print("LEAK SCAN FAILED: %d finding(s)" % len(findings))
        for f in findings:
            print("  " + f)
        return 1
    print("Leak scan passed: no private IPs, home-id-like numbers, or forbidden strings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
