"""Scripted `flwr chat`: send one or more prompts to the published app in ONE run series and print the replies.

Usage: PYTHONUTF8=1 uv run python scripts/chat_once.py "My goal: ..." "approve 1, 3" ...
Env: FAB=path/to/local.fab (run local build on SuperGrid)  APP=@lokilks/second-brain  FLWR_CHAT_SUPERLINK (default: supergrid)
Needs `uv run flwr login supergrid` first. Dev tool only; not part of the FAB.
"""

from __future__ import annotations

import os
import sys

from flwr.cli.chat.chat_app import parse_task_event, start_chat_run
from flwr.cli.constant import CHAT_SUPERGRID_CONNECTION_NAME
from flwr.cli.utils import flwr_cli_exc_handler, init_http_client_from_connection
from flwr.cli.flower_config import read_superlink_connection
from flwr.proto.control_pb2 import ListFederationsRequest, StreamRunEventsRequest


def main() -> None:
    app = os.environ.get("APP", "@lokilks/second-brain")
    conn = read_superlink_connection(os.environ.get("FLWR_CHAT_SUPERLINK", CHAT_SUPERGRID_CONNECTION_NAME))
    stub = init_http_client_from_connection(conn)
    try:
        with flwr_cli_exc_handler():
            feds = list(stub.ListFederations(ListFederationsRequest()).federations)
        federation = conn.federation or (feds[0].id if feds and hasattr(feds[0], "id") else None)
        series = None
        fab = open(os.environ["FAB"], "rb").read() if os.environ.get("FAB") else None  # test a local build, no publish
        for prompt in sys.argv[1:]:
            run_id, series = start_chat_run(stub, prompt, federation, series, app_spec=app, fab_content=fab)
            print(f"\n>>> {prompt}\n[run {run_id}, series {series}]")
            for res in stub.StreamRunEvents(StreamRunEventsRequest(run_id=run_id)):
                etype, payload = parse_task_event(res.task_event)
                if etype == "response.output_text.delta":
                    print(payload.get("delta", ""), end="", flush=True)
                elif etype in ("error", "response.failed") or "fail" in etype:
                    print(f"\n[{etype}] {payload}")
            print()
    finally:
        stub.close()


if __name__ == "__main__":
    main()
