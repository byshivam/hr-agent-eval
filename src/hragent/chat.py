"""Chat with the HR agent in the terminal.

Usage:
    PYTHONPATH=src python -m hragent.chat                 # as Priya Sharma (E1001)
    PYTHONPATH=src python -m hragent.chat --as E1002      # as Rahul Verma
    PYTHONPATH=src python -m hragent.chat --trace         # also print every tool call
"""

from __future__ import annotations

import argparse
import json

from hragent.agent import HRAgent
from hragent.hr_system import EMPLOYEES, HRSystem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as", dest="employee", default="E1001", choices=sorted(EMPLOYEES))
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--trace", action="store_true", help="show tool calls")
    args = parser.parse_args()

    hr = HRSystem(current_user=args.employee)
    agent = HRAgent(hr, prompt_version=args.prompt_version)
    print(f"Tayal Capital HR assistant — signed in as {EMPLOYEES[args.employee]['name']}. "
          f"Today is {hr.today:%A, %d %B %Y}. Type 'exit' to quit.\n")
    while True:
        try:
            message = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"exit", "quit"}:
            break
        if not message:
            continue
        response = agent.send(message)
        if args.trace:
            for step in response.tool_steps:
                status = "ok" if step.ok else "error"
                print(f"  ↳ {step.tool}({json.dumps(step.args)}) → {status}: {json.dumps(step.result)[:200]}")
        print(f"hr  > {response.answer}\n")


if __name__ == "__main__":
    main()
