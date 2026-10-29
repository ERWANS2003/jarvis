"""Runner de tests minimaliste, sans dependance externe.

Usage :  .venv\\Scripts\\python.exe tests\\run_tests.py
"""

from __future__ import annotations

import importlib
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = [
    "tests.test_text",
    "tests.test_memory",
    "tests.test_tools",
    "tests.test_providers",
    "tests.test_vad",
    "tests.test_tts",
    "tests.test_stt",
    "tests.test_graph",
    "tests.test_config",
    "tests.test_plugins",
    "tests.test_gui",
    "tests.test_gui_window",
    "tests.test_web",
    "tests.test_orb",
    "tests.test_orb_render",
    "tests.test_wake",
    "tests.test_pc",
    "tests.test_files",
    "tests.test_websites",
    "tests.test_intents",
    "tests.test_assistant",
    "tests.test_smart",
    "tests.test_hearing",
    "tests.test_orb_life",
    "tests.test_briefing",
    "tests.test_settings",
    "tests.test_cli",
    "tests.test_i18n",
]


def main() -> int:
    passed = failed = 0
    failures: list[str] = []
    for name in MODULES:
        module_path = ROOT / (name.replace(".", "/") + ".py")
        if not module_path.exists():
            print(f"skip  {name} (pas encore ecrit)")
            continue
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            failed += 1
            failures.append(f"{name}: import impossible ({exc})")
            traceback.print_exc()
            continue
        tests = [
            (n, f) for n, f in vars(module).items()
            if n.startswith("test_") and callable(f)
            and getattr(f, "__module__", name) == name
        ]
        for test_name, func in sorted(tests):
            label = f"{name}.{test_name}"
            try:
                if inspect.signature(func).parameters:
                    continue
                func()
                passed += 1
                print(f"ok    {label}")
            except Exception as exc:
                failed += 1
                failures.append(f"{label}: {exc}")
                print(f"FAIL  {label}: {exc}")
                traceback.print_exc()
    print()
    if failures:
        print("ECHECS :")
        for item in failures:
            print("  -", item)
    print(f"{passed} reussis, {failed} echoues")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
