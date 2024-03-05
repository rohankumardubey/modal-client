# Copyright Modal Labs 2023
import contextlib
import io
import multiprocessing
import platform
import sys
from multiprocessing import Queue
from multiprocessing.context import SpawnProcess
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Set, Tuple, TypeVar

from synchronicity import Interface

from modal_utils.async_utils import TaskContext, asyncify, synchronize_api, synchronizer
from modal_utils.logger import logger

from ._output import OutputManager, get_app_logs_loop
from ._watcher import watch
from .cli.import_refs import import_stub
from .client import HEARTBEAT_INTERVAL, _Client
from .config import config
from .runner import _heartbeat, serve_update

if TYPE_CHECKING:
    from .stub import _Stub
else:
    _Stub = TypeVar("_Stub")


def _run_serve(stub_ref: str, existing_app_id: Optional[str], is_ready: Queue, environment_name: str):
    # subprocess entrypoint
    _stub = import_stub(stub_ref)
    blocking_stub = synchronizer._translate_out(_stub, Interface.BLOCKING)
    serve_update(blocking_stub, existing_app_id, is_ready, environment_name)


async def _restart_serve(
    stub_ref: str, existing_app_id: str, environment_name: str, timeout: float = 5.0
) -> Tuple[str, SpawnProcess]:
    ctx = multiprocessing.get_context("spawn")  # Needed to reload the interpreter
    is_ready = ctx.Queue()
    p = ctx.Process(target=_run_serve, args=(stub_ref, existing_app_id, is_ready, environment_name))
    p.start()
    app_id = is_ready.get(timeout)
    # TODO(erikbern): we don't fail if the above times out, but that's somewhat intentional, since
    # the child process might build a huge image or similar
    return app_id, p


async def _terminate(proc: Optional[SpawnProcess], output_mgr: OutputManager, timeout: float = 5.0):
    if proc is None:
        return
    try:
        proc.terminate()
        await asyncify(proc.join)(timeout)
        if proc.exitcode is not None:
            output_mgr.print_if_visible(f"Serve process {proc.pid} terminated")
        else:
            output_mgr.print_if_visible(
                f"[red]Serve process {proc.pid} didn't terminate after {timeout}s, killing it[/red]"
            )
            proc.kill()
    except ProcessLookupError:
        pass  # Child process already finished


def _get_clean_stub_description(stub_ref: str) -> str:
    # If possible, consider the 'ref' argument the start of the app's args. Everything
    # before it Modal CLI cruft (eg. `modal serve --timeout 1.0`).
    try:
        func_ref_arg_idx = sys.argv.index(stub_ref)
        return " ".join(sys.argv[func_ref_arg_idx:])
    except ValueError:
        return " ".join(sys.argv)


@contextlib.asynccontextmanager
async def _serve_stub(
    stub: "_Stub",
    stub_ref: str,
    stdout: Optional[io.TextIOWrapper] = None,
    show_progress: bool = True,
    _watcher: Optional[AsyncGenerator[Set[str], None]] = None,  # for testing
    environment_name: Optional[str] = None,
) -> AsyncGenerator["_Stub", None]:
    if environment_name is None:
        environment_name = config.get("environment")

    client = await _Client.from_env()
    output_mgr = OutputManager(stdout, show_progress, "Running app...")

    if _watcher is not None:
        watcher = _watcher  # Only used by tests
    else:
        mounts_to_watch = stub._get_watch_mounts()
        watcher = watch(mounts_to_watch, output_mgr)

    async with TaskContext(grace=config["logs_timeout"]) as tc:
        app_id, curr_proc = await _restart_serve(stub_ref, existing_app_id=None, environment_name=environment_name)
        # Start heartbeats loop to keep the client alive
        tc.infinite_loop(lambda: _heartbeat(client, app_id), sleep=HEARTBEAT_INTERVAL)

        # Start logs loop
        tc.create_task(get_app_logs_loop(app_id, client, output_mgr))

        with output_mgr.show_status_spinner():
            if platform.system() == "Windows":
                async for _ in watcher:
                    output_mgr.print_if_visible(
                        "Live-reload skipped. This feature is currently unsupported on Windows."
                    )
            else:
                try:
                    async for trigger_files in watcher:
                        logger.debug(f"The following files triggered an app update: {', '.join(trigger_files)}")
                        await _terminate(curr_proc, output_mgr)
                        _, curr_proc = await _restart_serve(
                            stub_ref, existing_app_id=app_id, environment_name=environment_name
                        )
                finally:
                    await _terminate(curr_proc, output_mgr)

            yield app_id


serve_stub = synchronize_api(_serve_stub)
