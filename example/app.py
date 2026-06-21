import asyncio
import json
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import StreamingResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, REGISTRY

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from example.ollama_provider import OllamaProducer
from stream_guard.receipt import CancelCategory
from stream_guard.observability.logging_setup import get_logger
from stream_guard.observability.tracing import init_tracing
from stream_guard.receipt_sink import ReceiptSink


init_tracing()
logger = get_logger()
app = FastAPI()

receipt_sink = ReceiptSink("receipts/stream_receipts.jsonl")
# ============================================================
# Metrics Endpoint
# ============================================================

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/metrics.json")
def metrics_json():
    metrics = {}
    for metric in REGISTRY.collect():
        metrics[metric.name] = {
            "help": metric.documentation,
            "type": metric.type,
            "samples": [
                {"name": s.name, "labels": s.labels, "value": s.value}
                for s in metric.samples
            ]
        }
    return metrics


# ============================================================
# HTTP Streaming Endpoint
# ============================================================

@app.get("/stream")
async def stream_http(
    request: Request,
    prompt: str = Query(...),
    model: str = Query("llama3"),
):
    producer = OllamaProducer(model=model, prompt=prompt)

    committed_q = asyncio.Queue()
    writer = ChunkWriter(committed_q)

    session = StreamSession(
        producer=producer,
        writer=writer,
        speculative_buffer_limit=8,
        max_inflight_commits=16,
        timeout_seconds=None,
    )

    session.start()
    handle = session.handle
    receipt_persisted = False
    receipt_persist_lock = asyncio.Lock()

    async def persist_receipt_once(event_name: str) -> None:
        nonlocal receipt_persisted
        async with receipt_persist_lock:
            if receipt_persisted:
                return
            receipt = await session.shutdown()
            receipt_sink.write(receipt)
            logger.info(event_name, extra=receipt.__dict__)
            receipt_persisted = True

    async def token_generator():
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("http_client_disconnected")
                    session.cancel(
                        reason="client_disconnected",
                        category=CancelCategory.USER,
                    )
                    break

                token = await handle.read()

                if token is None:
                    logger.info("http_eos_observed")
                    break

                yield token

        except asyncio.CancelledError:
            session.cancel(
                reason="transport_cancelled",
                category=CancelCategory.USER,
            )
            asyncio.create_task(
                persist_receipt_once("http_streaming_task_cancelled")
            )
            raise

        finally:
            try:
                await asyncio.shield(
                    persist_receipt_once("http_stream_finalized")
                )
            except asyncio.CancelledError:
                asyncio.create_task(
                    persist_receipt_once(
                        "http_stream_finalized_cancelled_cleanup"
                    )
                )

    return StreamingResponse(
        token_generator(),
        media_type="text/plain",
    )


# ============================================================
# WebSocket Streaming Endpoint
# ============================================================

@app.websocket("/ws")
async def stream_ws(websocket: WebSocket):
    await websocket.accept()

    prompt = websocket.query_params.get("prompt")
    model = websocket.query_params.get("model", "llama3")

    if not prompt:
        await websocket.close(code=1008)
        return

    producer = OllamaProducer(model=model, prompt=prompt)

    committed_q = asyncio.Queue()
    writer = ChunkWriter(committed_q)

    session = StreamSession(
        producer=producer,
        writer=writer,
        speculative_buffer_limit=8,
        max_inflight_commits=16,
        timeout_seconds=None,
    )

    session.start()
    handle = session.handle
    receipt_persisted = False
    receipt_persist_lock = asyncio.Lock()

    async def persist_receipt_once(event_name: str) -> None:
        nonlocal receipt_persisted
        async with receipt_persist_lock:
            if receipt_persisted:
                return
            receipt = await session.shutdown()
            receipt_sink.write(receipt)
            logger.info(event_name, extra=receipt.__dict__)
            receipt_persisted = True

    try:
        while True:
            token = await handle.read()

            if token is None:
                logger.info("ws_eos_observed")
                break

            await websocket.send_text(token)

    except WebSocketDisconnect:
        session.cancel(
            reason="client_disconnected",
            category=CancelCategory.USER,
        )
        await persist_receipt_once("ws_client_disconnected")

    except asyncio.CancelledError:
        session.cancel(
            reason="transport_cancelled",
            category=CancelCategory.USER,
        )
        asyncio.create_task(
            persist_receipt_once("ws_streaming_task_cancelled")
        )
        raise

    finally:
        try:
            await asyncio.shield(
                persist_receipt_once("ws_stream_finalized")
            )
        except asyncio.CancelledError:
            asyncio.create_task(
                persist_receipt_once(
                    "ws_stream_finalized_cancelled_cleanup"
                )
            )
