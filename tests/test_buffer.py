"""Tests for the debounced event buffer."""

import asyncio

import pytest

import src.agent.buffer as buffer_module
from src.agent.buffer import EventBuffer


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch):
    monkeypatch.setattr(buffer_module, "EVENT_BUFFER_TIMEOUT", 0.02)


async def test_flush_after_quiet_period():
    flushed = []

    async def callback(events):
        flushed.append(events)

    buffer = EventBuffer(callback)
    buffer.add_event((1, {"n": 1}))
    await asyncio.sleep(0.05)

    assert flushed == [[(1, {"n": 1})]]
    assert buffer.buffer == []


async def test_new_event_restarts_timer():
    flushed = []

    async def callback(events):
        flushed.append(events)

    buffer = EventBuffer(callback)
    buffer.add_event((1, {"n": 1}))
    await asyncio.sleep(0.01)
    buffer.add_event((2, {"n": 2}))
    await asyncio.sleep(0.01)

    assert flushed == []
    await asyncio.sleep(0.03)

    assert flushed == [[(1, {"n": 1}), (2, {"n": 2})]]


async def test_callback_failure_restores_events():
    async def callback(events):
        raise RuntimeError("boom")

    buffer = EventBuffer(callback)
    buffer.add_event((1, {"n": 1}))

    await buffer.force_flush()

    assert buffer.buffer == [(1, {"n": 1})]
