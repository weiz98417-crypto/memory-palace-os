"""CPU runtime budget tests for the local bge-m3 embedding adapter."""

from __future__ import annotations

import os

import pytest

from memory_palace.tools import embedding_client


def test_default_cpu_thread_budget_is_bounded(monkeypatch):
    monkeypatch.delenv("EMBEDDING_CPU_THREADS", raising=False)

    assert embedding_client._cpu_thread_budget() == min(4, os.cpu_count() or 1)


def test_operator_can_override_the_cpu_thread_budget(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CPU_THREADS", "2")

    assert embedding_client._cpu_thread_budget() == 2


@pytest.mark.parametrize("value", ["0", "-1", "many", "1.5", ""])
def test_invalid_cpu_thread_budget_is_rejected(monkeypatch, value):
    monkeypatch.setenv("EMBEDDING_CPU_THREADS", value)

    if value == "":
        assert embedding_client._cpu_thread_budget() == min(4, os.cpu_count() or 1)
        return
    with pytest.raises(RuntimeError, match="positive integer"):
        embedding_client._cpu_thread_budget()


def test_thread_budget_is_published_to_the_process_environment(monkeypatch):
    monkeypatch.delenv("EMBEDDING_CPU_THREADS", raising=False)
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        monkeypatch.delenv(variable, raising=False)

    threads = embedding_client._configure_cpu_threads()

    assert os.environ["OMP_NUM_THREADS"] == str(threads)
    assert os.environ["MKL_NUM_THREADS"] == str(threads)
    assert os.environ["OPENBLAS_NUM_THREADS"] == str(threads)


def test_explicit_operator_thread_count_is_not_overwritten(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")

    embedding_client._configure_cpu_threads()

    assert os.environ["OMP_NUM_THREADS"] == "1"


def test_module_exposes_a_stable_thread_budget(monkeypatch):
    monkeypatch.delenv("EMBEDDING_CPU_THREADS", raising=False)

    assert embedding_client.CPU_THREADS == embedding_client._cpu_thread_budget()
