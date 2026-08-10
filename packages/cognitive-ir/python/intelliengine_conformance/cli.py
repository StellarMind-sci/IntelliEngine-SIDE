from __future__ import annotations

import argparse
import json
import sys

from .consumer import ConformanceConsumer, ConsumerError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run IntelliEngine Python conformance fixtures")
    parser.add_argument("--profile-root", required=True)
    arguments = parser.parse_args(argv)
    try:
        results = ConformanceConsumer(arguments.profile_root).run_all()
    except (ConsumerError, OSError, ValueError) as error:
        print(f"conformance consumer failed: {error}", file=sys.stderr)
        return 1
    for result in results:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
