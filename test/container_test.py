import asyncio
import time

import pytest

from polyester import Client, Session
from polyester.container_entrypoint import main
from polyester.function import Function, pack_input_buffer_item
from polyester.proto import api_pb2
from polyester.test_support import SLEEP_DELAY

EXTRA_TOLERANCE_DELAY = 0.08
OUTPUT_BUFFER = "output_buffer_id"
INPUT_BUFFER = "input_buffer_id"

session = Session()  # Just used for (de)serialization


def _get_inputs(client):
    item = pack_input_buffer_item(session.serialize((42,)), session.serialize({}), OUTPUT_BUFFER)

    return [
        api_pb2.BufferReadResponse(item=item, status=api_pb2.BufferReadResponse.BufferReadStatus.SUCCESS),
        api_pb2.BufferReadResponse(
            item=api_pb2.BufferItem(EOF=True), status=api_pb2.BufferReadResponse.BufferReadStatus.SUCCESS
        ),
    ]


def _get_output(function_output_req: api_pb2.FunctionOutputRequest) -> api_pb2.GenericResult:
    output = api_pb2.GenericResult()
    function_output_req.buffer_req.item.data.Unpack(output)
    return output


async def _run_container(servicer, module_name, function_name):
    async with Client(servicer.remote_addr, api_pb2.ClientType.CONTAINER, ("ta-123", "task-secret")) as client:
        servicer.inputs = _get_inputs(client)

        # Note that main is a synchronous function, so we need to run it in a separate thread
        container_args = api_pb2.ContainerArguments(
            task_id="ta-123",
            function_id="fu-123",
            input_buffer_id=INPUT_BUFFER,
            session_id="se-123",
            module_name=module_name,
            function_name=function_name,
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, main, container_args, client)

        return client, servicer.outputs


@pytest.mark.asyncio
async def test_container_entrypoint_success(servicer):
    t0 = time.time()
    client, outputs = await _run_container(servicer, "polyester.test_support", "square")
    assert 0 <= time.time() - t0 < EXTRA_TOLERANCE_DELAY

    assert len(outputs) == 1
    assert isinstance(outputs[0], api_pb2.FunctionOutputRequest)

    output = _get_output(outputs[0])
    assert output.status == api_pb2.GenericResult.Status.SUCCESS
    session = Session()
    assert output.data == session.serialize(42 ** 2)


@pytest.mark.asyncio
async def test_container_entrypoint_async(servicer):
    t0 = time.time()
    client, outputs = await _run_container(servicer, "polyester.test_support", "square_async")
    print(time.time() - t0, outputs)
    assert SLEEP_DELAY <= time.time() - t0 < SLEEP_DELAY + EXTRA_TOLERANCE_DELAY

    assert len(outputs) == 1
    assert isinstance(outputs[0], api_pb2.FunctionOutputRequest)

    output = _get_output(outputs[0])
    assert output.status == api_pb2.GenericResult.Status.SUCCESS
    assert output.data == session.serialize(42 ** 2)


@pytest.mark.asyncio
async def test_container_entrypoint_sync_returning_async(servicer):
    t0 = time.time()
    client, outputs = await _run_container(servicer, "polyester.test_support", "square_sync_returning_async")
    assert SLEEP_DELAY <= time.time() - t0 < SLEEP_DELAY + EXTRA_TOLERANCE_DELAY

    assert len(outputs) == 1
    assert isinstance(outputs[0], api_pb2.FunctionOutputRequest)

    output = _get_output(outputs[0])
    assert output.status == api_pb2.GenericResult.Status.SUCCESS
    assert output.data == session.serialize(42 ** 2)


@pytest.mark.asyncio
async def test_container_entrypoint_failure(servicer):
    client, outputs = await _run_container(servicer, "polyester.test_support", "raises")

    assert len(outputs) == 1
    assert isinstance(outputs[0], api_pb2.FunctionOutputRequest)

    output = _get_output(outputs[0])
    assert output.status == api_pb2.GenericResult.Status.FAILURE
    assert output.exception in ["Exception('Failure!')", "Exception('Failure!',)"]  # The 2nd is 3.6
    assert "Traceback" in output.traceback


def test_import_function_dynamically():
    f = Function.get_function("polyester.test_support", "square")
    assert f.raw_f(42) == 42 * 42
