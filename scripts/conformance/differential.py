from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import signal
from typing import Any


class GateError(Exception):
    def __init__(self, code: str, path: str = "", consumer: str = "runner", status: str | None = None) -> None:
        super().__init__(code)
        self.code, self.path, self.consumer, self.status = code, path, consumer, status or code.rsplit(".", 1)[-1]


def scalar_string(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF:
            if index + 1 >= len(value): raise ValueError("unpaired high surrogate")
            low = ord(value[index + 1])
            if not 0xDC00 <= low <= 0xDFFF: raise ValueError("unpaired high surrogate")
            result.append(chr(0x10000 + ((code - 0xD800) << 10) + low - 0xDC00)); index += 2; continue
        if 0xDC00 <= code <= 0xDFFF: raise ValueError("unpaired low surrogate")
        result.append(value[index]); index += 1
    return "".join(result)


def strict_json(raw: bytes, path: str) -> Any:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise GateError("conformance.malformed_json", path)
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            key = scalar_string(key)
            if key in result:
                raise GateError("conformance.malformed_json", path)
            result[key] = value
        return result
    try:
        text = raw.decode("utf-8", "strict")
        def integer(text: str) -> int:
            value = int(text)
            if abs(value) > 9_007_199_254_740_991: raise ValueError("unsafe integer")
            return value
        def number(text: str) -> float:
            value = float(text)
            if not math.isfinite(value): raise ValueError("nonfinite")
            return value
        value = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=number, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        def normalize(item: Any) -> Any:
            if isinstance(item, str): return scalar_string(item)
            if isinstance(item, list): return [normalize(child) for child in item]
            if isinstance(item, dict): return {key: normalize(child) for key, child in item.items()}
            return item
        return normalize(value)
    except GateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GateError("conformance.malformed_json", path) from error


def number_text(value: int | float) -> str:
    if isinstance(value, int):
        if abs(value) > 9_007_199_254_740_991:
            raise GateError("conformance.malformed_json")
        return str(value)
    if not math.isfinite(value):
        raise GateError("conformance.malformed_json")
    if value == 0:
        return "0"
    negative = value < 0
    number = -value if negative else value
    shortest = repr(number).lower()
    if "e" in shortest:
        mantissa, exponent_text = shortest.split("e")
        exponent = int(exponent_text)
        digits = mantissa.replace(".", "")
        position = (mantissa.index(".") if "." in mantissa else len(mantissa)) + exponent
        scientific = position - 1
        if -6 <= scientific < 21:
            if position <= 0:
                rendered = "0." + "0" * -position + digits
            elif position >= len(digits):
                rendered = digits + "0" * (position - len(digits))
            else:
                rendered = digits[:position] + "." + digits[position:]
        else:
            fraction = digits[1:].rstrip("0")
            rendered = digits[0] + (("." + fraction) if fraction else "") + f"e{scientific:+d}"
    else:
        rendered = shortest.removesuffix(".0")
    return ("-" if negative else "") + rendered


def jcs(value: Any) -> bytes:
    if value is None: return b"null"
    if value is True: return b"true"
    if value is False: return b"false"
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if isinstance(value, (int, float)): return number_text(value).encode()
    if isinstance(value, list): return b"[" + b",".join(jcs(item) for item in value) + b"]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda item: item.encode("utf-16-be", "surrogatepass"))
        return b"{" + b",".join(jcs(key) + b":" + jcs(value[key]) for key in keys) + b"}"
    raise GateError("conformance.malformed_json")


def safe(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
        raise GateError("conformance.unsafe_path", relative)
    candidate = (root / Path(*relative.split("/"))).resolve()
    try: candidate.relative_to(root)
    except ValueError as error: raise GateError("conformance.unsafe_path", relative) from error
    return candidate


def walk_refs(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            if key == "$ref" and isinstance(child, str):
                if child == "#": pass
                elif child.startswith("#/"):
                    if any("~" in token.replace("~0", "").replace("~1", "") for token in child[2:].split("/")):
                        raise GateError("conformance.external_reference", child_path)
                elif child.startswith("urn:intelliengine:schema:sha256:"):
                    digest = child.rsplit(":", 1)[-1]
                    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest): raise GateError("conformance.external_reference", child_path)
                else: raise GateError("conformance.external_reference", child_path)
            walk_refs(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value): walk_refs(child, f"{path}/{index}")


def references(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str): found.append(child)
            found.extend(references(child))
    elif isinstance(value, list):
        for child in value: found.extend(references(child))
    return found


def resolve_pointer(document: Any, reference: str) -> None:
    if reference == "#": return
    current = document
    for raw in reference[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(token)] if isinstance(current, list) else current[token]
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise GateError("conformance.external_reference", "/$ref") from error


def schema_valid(value: Any, schema: dict[str, Any]) -> bool:
    if "const" in schema and value != schema["const"]: return False
    if "enum" in schema and value not in schema["enum"]: return False
    kind = schema.get("type")
    if kind == "object" and not isinstance(value, dict): return False
    if kind == "array" and not isinstance(value, list): return False
    if kind == "string" and not isinstance(value, str): return False
    if kind == "integer" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer()): return False
    if isinstance(value, dict):
        if any(key not in value for key in schema.get("required", [])): return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and any(key not in properties for key in value): return False
        if any(key in value and not schema_valid(value[key], child) for key, child in properties.items()): return False
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]: return False
        if "items" in schema and any(not schema_valid(item, schema["items"]) for item in value): return False
    if isinstance(value, int) and "minimum" in schema and value < schema["minimum"]: return False
    if isinstance(value, str) and "pattern" in schema:
        import re
        if re.search(schema["pattern"], value) is None: return False
    if any(not schema_valid(value, child) for child in schema.get("allOf", [])): return False
    if "oneOf" in schema and sum(schema_valid(value, child) for child in schema["oneOf"]) != 1: return False
    if "if" in schema:
        branch = schema.get("then") if schema_valid(value, schema["if"]) else schema.get("else")
        if branch is not None and not schema_valid(value, branch): return False
    return True


def load_normative(profile_root: Path) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    if profile_root.is_symlink(): raise GateError("conformance.unsafe_path", "/profile-root")
    profile_root = profile_root.resolve()
    if profile_root.name != "1.0.0" or profile_root.parent.name != "profile": raise GateError("conformance.unsafe_path", "/profile-root")
    contract_root = profile_root.parents[1]
    lock_path = profile_root / "lock.json"
    if lock_path.is_symlink(): raise GateError("conformance.unsafe_path", "/lock")
    lock = strict_json(lock_path.read_bytes(), "/lock")
    locked: set[str] = set()
    documents: dict[str, Any] = {}
    for index, entry in enumerate(lock.get("entries", [])):
        if not isinstance(entry, dict) or entry.get("digest_kind") not in ("jcs_sha256", "raw_sha256"):
            raise GateError("conformance.invalid_manifest", f"/entries/{index}/digest_kind")
        relative = entry.get("path")
        if relative == "profile/1.0.0/lock.json": raise GateError("conformance.invalid_manifest", f"/entries/{index}/path")
        target = safe(contract_root, relative)
        if relative in locked: raise GateError("conformance.duplicate_lock", f"/entries/{index}/path")
        locked.add(relative)
        raw = target.read_bytes()
        value = strict_json(raw, relative) if target.suffix == ".json" else None
        digest = hashlib.sha256(raw if entry.get("digest_kind") == "raw_sha256" else jcs(value)).hexdigest()
        if digest != entry.get("sha256"): raise GateError("conformance.lock_mismatch", f"/entries/{index}/sha256")
        if value is not None: walk_refs(value); documents[relative] = value
    actual = {
        path.relative_to(contract_root).as_posix() for path in profile_root.rglob("*")
        if path.is_file() and path != lock_path
    }
    extra = sorted(actual - locked, key=lambda item: item.encode())
    if extra: raise GateError("conformance.unlocked_file", extra[0])
    missing = sorted(locked - actual, key=lambda item: item.encode())
    if missing: raise GateError("conformance.missing_locked_file", missing[0])
    lock_schema = documents.get("profile/1.0.0/schemas/lock.schema.json")
    if not isinstance(lock_schema, dict) or not schema_valid(lock, lock_schema): raise GateError("conformance.invalid_manifest", "/lock")
    digest_targets = {
        entry["sha256"]: entry["path"] for entry in lock["entries"]
        if entry["digest_kind"] == "jcs_sha256" and isinstance(documents.get(entry["path"]), dict)
        and documents[entry["path"]].get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    }
    scoped_claims: dict[str, set[str]] = {}
    for case_path, document in documents.items():
        if case_path.endswith("/case.json") and isinstance(document, dict) and isinstance(document.get("resources"), list):
            owned_prefix = case_path.rsplit("/", 1)[0] + "/"
            bundle: list[tuple[str, str]] = []
            for resource in document["resources"]:
                if not isinstance(resource, dict) or not isinstance(resource.get("claimed_sha256"), str): continue
                if not isinstance(resource.get("path"), str) or not resource["path"].startswith(owned_prefix):
                    raise GateError("conformance.external_reference", "/resources/path")
                resource_document = documents.get(resource.get("path"))
                if isinstance(resource_document, dict) and resource_document.get("$schema") == "https://json-schema.org/draft/2020-12/schema":
                    bundle.append((resource["path"], resource["claimed_sha256"]))
            claims = {digest for _path, digest in bundle}
            for resource_path, _digest in bundle: scoped_claims.setdefault(resource_path, set()).update(claims)
    graph: dict[str, set[str]] = {path: set() for path in documents}
    for source, document in documents.items():
        for reference in references(document):
            if reference.startswith("#"): resolve_pointer(document, reference)
            elif reference.startswith("urn:intelliengine:schema:sha256:"):
                digest = reference.rsplit(":", 1)[-1]
                if digest not in digest_targets and digest not in scoped_claims.get(source, set()): raise GateError("conformance.external_reference", "/$ref")
                if digest in digest_targets: graph[source].add(digest_targets[digest])
    visiting: set[str] = set(); visited: set[str] = set()
    def acyclic(node: str) -> bool:
        if node in visiting: return False
        if node in visited: return True
        visiting.add(node)
        if any(not acyclic(target) for target in graph.get(node, ())): return False
        visiting.remove(node); visited.add(node); return True
    if any(not acyclic(node) for node in graph): raise GateError("conformance.external_reference", "/$ref")
    manifest = strict_json((profile_root / "fixtures/manifest.json").read_bytes(), "/manifest")
    expected_schema = strict_json((profile_root / "schemas/expected-result.schema.json").read_bytes(), "/expected-schema")
    ids: list[str] = []
    expected: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(manifest.get("cases", [])):
        case_relative = f"profile/1.0.0/fixtures/{entry.get('path', '')}"
        case = strict_json(safe(contract_root, case_relative).read_bytes(), f"/cases/{index}")
        case_id = case.get("case_id")
        if case_id != entry.get("case_id") or case_id in expected: raise GateError("conformance.invalid_manifest", f"/cases/{index}")
        row = {"case_id": case_id, **case.get("expected", {})}
        validate_row(row, case_id, "runner", expected_schema)
        ids.append(case_id); expected[case_id] = row
    ids.sort(key=lambda item: item.encode())
    return ids, expected, expected_schema


REQUIRED = {"case_id", "contract_id", "contract_version", "issues", "mode", "object_result", "operation_outcome", "profile_version", "raw_sha256", "work_units_consumed"}
LEGAL = {("valid", "succeeded"), ("invalid", "succeeded"), ("opaque", "succeeded"), ("opaque", "indeterminate"), ("opaque", "policy_denied"), ("not_evaluated", "resource_exhausted"), ("not_evaluated", "indeterminate")}


def validate_row(row: Any, case_id: str, consumer: str, expected_schema: dict[str, Any]) -> None:
    if not isinstance(row, dict) or set(row) not in (REQUIRED, REQUIRED | {"jcs_sha256"}): raise GateError("conformance.invalid_projection", f"/{case_id}", consumer)
    if row.get("case_id") != case_id or (row.get("object_result"), row.get("operation_outcome")) not in LEGAL: raise GateError("conformance.invalid_projection", f"/{case_id}", consumer)
    for field in ("raw_sha256", "jcs_sha256"):
        if field in row and (not isinstance(row[field], str) or len(row[field]) != 64 or any(char not in "0123456789abcdef" for char in row[field])): raise GateError("conformance.invalid_projection", f"/{case_id}/{field}", consumer)
    units = row["work_units_consumed"]
    if isinstance(units, bool) or not isinstance(units, (int, float)) or not math.isfinite(float(units)) or not float(units).is_integer() or units < 0 or not isinstance(row["issues"], list): raise GateError("conformance.invalid_projection", f"/{case_id}", consumer)
    for index, issue in enumerate(row["issues"]):
        if not isinstance(issue, dict) or set(issue) != {"code", "path", "severity"} or issue["severity"] not in ("error", "warning", "info"): raise GateError("conformance.invalid_projection", f"/{case_id}/issues/{index}", consumer)
    jcs(row)
    if not schema_valid({key: value for key, value in row.items() if key != "case_id"}, expected_schema): raise GateError("conformance.invalid_projection", f"/{case_id}", consumer)


def execute(command: list[str], consumer: str, timeout: float, root: Path) -> bytes:
    environment = {name: os.environ[name] for name in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME") if name in os.environ}
    environment.update({"PYTHONPATH": str(root / "packages/cognitive-ir/python"), "PYTHONUTF8": "1", "NO_PROXY": "", "no_proxy": "", "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "PIP_NO_INDEX": "1", "PYTHONNOUSERSITE": "1", "npm_config_offline": "true"})
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=os.name != "nt", creationflags=creationflags)
    job = None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class BasicLimits(ctypes.Structure):
            _fields_ = [("per_process", ctypes.c_longlong), ("per_job", ctypes.c_longlong), ("flags", wintypes.DWORD),
                        ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class IoCounters(ctypes.Structure): _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_mem", ctypes.c_size_t), ("job_mem", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits(); limits.basic.flags = 0x00002000
        if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            if job: kernel.CloseHandle(job)
            job = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}; exceeded: list[str] = []
    def drain(name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk: return
            if len(buffers[name]) + len(chunk) > 1_048_576:
                exceeded.append(name); return
            buffers[name].extend(chunk)
    threads = [threading.Thread(target=drain, args=(name, stream), daemon=True) for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))]
    for thread in threads: thread.start()
    deadline = time.monotonic() + timeout
    while process.poll() is None and not exceeded and time.monotonic() < deadline: time.sleep(0.005)
    timed_out = process.poll() is None and not exceeded
    if process.poll() is None:
        try:
            if os.name == "nt" and job: kernel.CloseHandle(job); job = None
            elif os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            else: os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError): process.kill()
    try: process.wait(timeout=2)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
    for thread in threads: thread.join(timeout=0.5)
    if job: kernel.CloseHandle(job)
    for stream, thread in zip((process.stdout, process.stderr), threads):
        if stream and not thread.is_alive(): stream.close()
    if exceeded:
        name = exceeded[0]
        code = "conformance.output_invalid" if name == "stdout" else "conformance.consumer_crashed"
        raise GateError(code, "/", consumer, f"{name}_limit")
    if timed_out: raise GateError("conformance.consumer_timeout", "/", consumer, "timeout")
    if buffers["stderr"]: raise GateError("conformance.consumer_crashed", "/", consumer, "stderr_nonempty")
    if process.returncode: raise GateError("conformance.consumer_crashed", "/", consumer, "exit_nonzero")
    return bytes(buffers["stdout"])


def parse_ndjson(raw: bytes, consumer: str, ids: list[str], expected_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if raw.startswith(b"\xef\xbb\xbf"): raise GateError("conformance.malformed_ndjson", "/", consumer)
    rows: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(raw.splitlines()):
        if not line.strip(): raise GateError("conformance.malformed_ndjson", f"/{index}", consumer)
        try: row = strict_json(line, f"/{index}")
        except GateError as error: raise GateError("conformance.malformed_ndjson", f"/{index}", consumer) from error
        case_id = row.get("case_id") if isinstance(row, dict) else None
        if case_id in rows: raise GateError("conformance.fixture_set_mismatch", "/case_id", consumer, "duplicate_case")
        if case_id not in ids: raise GateError("conformance.fixture_set_mismatch", "/case_id", consumer, "extra_case")
        validate_row(row, case_id, consumer, expected_schema); rows[case_id] = row
    missing = [case_id for case_id in ids if case_id not in rows]
    if missing: raise GateError("conformance.fixture_set_mismatch", f"/{missing[0]}", consumer, "missing_case")
    return rows


def pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def first_difference(expected: Any, actual: Any, path: str = "") -> str | None:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        return None if number_text(expected) == number_text(actual) else (path or "/")
    if type(expected) is not type(actual): return path or "/"
    if isinstance(expected, dict):
        keys = sorted(set(expected) | set(actual), key=lambda key: key.encode("utf-8"))
        for key in keys:
            child = f"{path}/{pointer_part(key)}"
            if key not in expected or key not in actual: return child
            difference = first_difference(expected[key], actual[key], child)
            if difference is not None: return difference
        return None
    if isinstance(expected, list):
        for index in range(max(len(expected), len(actual))):
            child = f"{path}/{index}"
            if index >= len(expected) or index >= len(actual): return child
            difference = first_difference(expected[index], actual[index], child)
            if difference is not None: return difference
        return None
    return None if expected == actual else (path or "/")


def normalized(error: GateError, case_count: int) -> tuple[int, dict[str, Any]]:
    offline = {"unsafe_path", "unlocked_file", "external_reference", "lock_mismatch", "missing_locked_file", "duplicate_lock", "invalid_manifest", "malformed_json"}
    code = error.code
    status = error.status
    if status in offline:
        code = "conformance.offline_boundary_violation"
    elif code in ("conformance.malformed_ndjson", "conformance.invalid_projection"):
        code = "conformance.output_invalid"
        status = "malformed_ndjson" if error.code.endswith("malformed_ndjson") else "invalid_projection"
    issue: dict[str, Any] = {"code": code, "consumer": error.consumer if error.consumer in ("runner", "typescript", "python") else "runner", "status": status}
    if error.path and code != "conformance.offline_boundary_violation":
        last = error.path.strip("/").split("/")[0]
        if last and code in ("conformance.result_mismatch", "conformance.fixture_set_mismatch"): issue["case_id"] = last
        issue["path"] = error.path
    issue["details_sha256"] = hashlib.sha256(f"{code}|{status}|{issue.get('path','')}".encode()).hexdigest()
    return 1, {"report_version": "1.0.0", "profile_version": "1.0.0", "status": "failed", "case_count": case_count, "issues": [issue]}


def run_gate(profile_root: Path, commands: dict[str, list[str]], *, timeout_seconds: float = 30) -> tuple[int, dict[str, Any]]:
    case_count = 0
    try:
        ids, expected, expected_schema = load_normative(profile_root); case_count = len(ids)
        outputs = {
            consumer: parse_ndjson(execute(commands[consumer], consumer, timeout_seconds, Path(__file__).resolve().parents[2]), consumer, ids, expected_schema)
            for consumer in ("typescript", "python")
        }
        for case_id in ids:
            for consumer, rows in outputs.items():
                difference = first_difference(expected[case_id], rows[case_id])
                if difference is not None: raise GateError("conformance.result_mismatch", f"/{pointer_part(case_id)}{difference}", consumer, "expected_mismatch")
            difference = first_difference(outputs["typescript"][case_id], outputs["python"][case_id])
            if difference is not None: raise GateError("conformance.result_mismatch", f"/{pointer_part(case_id)}{difference}", "runner", "consumer_mismatch")
        return 0, {"report_version": "1.0.0", "profile_version": "1.0.0", "status": "passed", "case_count": case_count, "issues": []}
    except Exception as error:
        failure = error if isinstance(error, GateError) else GateError("conformance.offline_boundary_violation", status="io_error")
        return normalized(failure, case_count)


def main(argv: list[str] | None = None) -> int:
    def positive_finite(value: str) -> float:
        number = float(value)
        if not math.isfinite(number) or number <= 0: raise argparse.ArgumentTypeError("must be finite and greater than zero")
        return number
    def node_executable(value: str) -> str:
        if Path(value).name.lower() not in ("node", "node.exe"): raise argparse.ArgumentTypeError("must name the Node executable")
        return value
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", required=True); parser.add_argument("--node", type=node_executable, default="node")
    parser.add_argument("--timeout-seconds", type=positive_finite, default=30.0)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    fixed_profile = (root / "packages/cognitive-ir/contracts/profile/1.0.0").resolve()
    if Path(args.profile_root).resolve() != fixed_profile:
        parser.error("--profile-root must select the repository portable profile")
    profile = str(fixed_profile)
    commands = {"typescript": [args.node, str(root / "packages/cognitive-ir/src/conformance-ts/cli.ts"), "--profile-root", profile], "python": [sys.executable, "-B", "-m", "intelliengine_conformance.cli", "--profile-root", profile]}
    code, report = run_gate(Path(args.profile_root), commands, timeout_seconds=args.timeout_seconds)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
