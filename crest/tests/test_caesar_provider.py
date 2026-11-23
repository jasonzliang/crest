"""Offline Caesar protocol, isolation, and SDK accounting checks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import time

import pytest

from crest.providers import caesar
from crest.providers import caesar_worker as worker

ROME = str(Path(__file__).resolve().parents[3] / "rome")


@pytest.fixture(autouse=True)
def _restore_litellm_cost_map_env(monkeypatch):
    # worker._runtime setdefaults this for its dedicated subprocess; undo it after each in-process test.
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")


# Importing the Rome stack costs ~5 s per process; keep every test that loads it on one xdist worker.
ROME_WORKER = pytest.mark.xdist_group("rome")


def rome_class(tmp_path, module, name):
    """Import a Rome class through the worker runtime, as the real worker does."""
    with worker._runtime({"rome_path": ROME}, worker.UsageAudit(5, tmp_path / "setup-usage.json")):
        return getattr(importlib.import_module(module), name)


def _options(model=worker.SOL, tokens=100):
    return SimpleNamespace(json_data={"model": model, "messages": [], "max_completion_tokens": tokens})


class FakeAgent:
    def perceive(self): return "content", []


class Clock:
    """A settable monotonic clock: Caesar has one wall-clock deadline; phases never stop on time."""
    def __init__(self, now=0): self.now = now
    def monotonic(self): return self.now
    def advance(self, seconds): self.now += seconds


class Transient(Exception):
    status_code = 520
    response = SimpleNamespace(headers={})
    body = {"retryable": True, "retry_after": 60}


def _failing_sdk(sent, error=Transient):
    """A fake SDK client whose every request fails after being counted as sent."""
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise error()
    return SDK


class Job:
    def __init__(self, directory, state=None):
        self.directory = directory
        self.key = "a" * 64
        self.state = state or {}
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, **changes):
        self.state.update(changes)


def artifact(**changes):
    return {"abstract": "An abstract.", "artifact": "Full finding [1], including its last line.",
            "sources": {"https://example.test/paper": 1}, "num_drafts": 3,
            "metadata": {"synthesis_queries": 15}, **changes}


def completed():
    return {"status": "completed", "result": worker.extract_result(
        artifact(), "gpt-6.1-sol", {"input_tokens": 100, "output_tokens": 20,
        "cost_usd": .0004, "unknown_cost": False, "successful_calls": 1})}


def test_preset_uses_requested_models_and_isolates_chroma_and_output(tmp_path):
    first = worker.build_config("Q", {}, tmp_path / "one", "abc")
    second = worker.build_config("Q", {"exploration_model": "custom-explore", "kb_model": "custom-kb"}, tmp_path / "two", "def")
    assert first["CaesarAgent"]["max_iterations"] == 250
    assert first["CaesarAgent"]["max_depth"] == 6
    assert first["CaesarAgent"]["use_quick_explore"] is False
    assert first["CaesarAgent"]["quick_explore_insights"] is True
    assert first["CaesarAgent"]["quick_explore_workers"] == 2
    assert first["CaesarAgent"]["adapt_role"] is True
    assert first["ArtifactSynthesizer"]["synthesis_merge_artifacts"] is True
    assert first["CaesarAgent"]["additional_starting_queries"] == 11
    assert first["CaesarAgent"]["max_web_searches"] == 5
    assert first["ArtifactSynthesizer"]["synthesis_drafts"] == 3
    assert first["ArtifactSynthesizer"]["synthesis_iterations"] == 15
    assert first["ArtifactSynthesizer"]["synthesis_top_k"] == 50
    assert first["ArtifactSynthesizer"]["synthesis_generate_images"] == 0
    assert first["ArtifactSynthesizer"]["synthesis_merge_clarify"] is False
    assert first["BraveSearch"]["use_ddgs"] is True
    assert first["ChromaClientManager"]["enable_reranking"] is True
    assert first["LLMHandler"]["model"] == "gpt-6.1-sol"
    assert first["LLMHandler"]["cost_limit"] == 5
    assert first["LLMHandler"]["max_completion_tokens"] == 32768
    assert first["LLMHandler"]["timeout"] == 1200
    assert first["CaesarAgent"]["exploration_llm_config"]["timeout"] == 1200
    assert first["LLMHandler"]["max_input_tokens"] == 64000
    assert first["CaesarAgent"]["exploration_llm_config"]["max_completion_tokens"] == 2000
    assert first["CaesarAgent"]["exploration_llm_config"]["model"] == "gpt-6-luna"
    assert first["ChromaClientManager"]["model"] == "gpt-6-luna"
    assert second["CaesarAgent"]["exploration_llm_config"]["model"] == "custom-explore"
    assert second["ChromaClientManager"]["model"] == "custom-kb"
    assert first["ChromaClientManager"]["collection_name"] != second["ChromaClientManager"]["collection_name"]
    assert first["ChromaServerManager"]["persist_path"] != second["ChromaServerManager"]["persist_path"]
    assert first["AgentMemory"]["enabled"] is False


def test_extract_result_keeps_the_abstract_out_of_the_answer_but_in_the_raw_artifact():
    result = completed()["result"]
    assert "An abstract." not in result["text"] and result["raw"]["artifact"]["abstract"] == "An abstract."
    assert result["text"].startswith("Full finding")  # The main text opens the answer; the abstract is never counted or judged.
    assert "including its last line." in result["text"]
    assert "[1] https://example.test/paper" in result["text"]
    assert result["citations"] == [{"url": "https://example.test/paper", "title": "[1]"}]
    assert result["cost_usd"] == .0004
    assert result["cost_estimated"] is True
    assert result["raw"]["artifact"]["sources"] == artifact()["sources"]


@pytest.mark.parametrize("value", [None, {}, artifact(artifact=""), artifact(num_drafts=0), artifact(num_drafts=1), artifact(metadata={"synthesis_queries": 0})])
def test_extract_rejects_empty_or_incomplete_artifact(value):
    with pytest.raises(ValueError):
        worker.extract_result(value, "gpt-6.1-sol", {})


def test_unknown_audit_cost_is_not_zero():
    result = worker.extract_result(artifact(), "gpt-6.1-sol", {"cost_usd": 2, "unknown_cost": True})
    assert result["cost_usd"] is None
    assert result["warnings"]


def test_identity_tracks_rome_source_version_and_commit_without_reading_env(tmp_path, monkeypatch):
    (tmp_path / "caesar").mkdir()
    source = tmp_path / "caesar" / "caesar_agent.py"
    source.write_text("version = 1\n")
    (tmp_path / ".env").write_text("never include credentials")
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname="caesar-agent"\nversion="0.4.31"\n')
    monkeypatch.setattr(caesar.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="1a297af410063ef44e270bf727a7d4ee0ccc72d9\n"))
    old = caesar.identity_metadata({"rome_path": str(tmp_path)})
    assert old["rome_source_version"] == "0.4.31"
    assert old["rome_git_commit"] == "1a297af410063ef44e270bf727a7d4ee0ccc72d9"
    assert "credentials" not in json.dumps(old)
    source.write_text("version = 2\n")
    changed_source = caesar.identity_metadata({"rome_path": str(tmp_path)})
    assert old != changed_source
    project.write_text('[project]\nname="caesar-agent"\nversion="0.4.32"\n')
    assert changed_source != caesar.identity_metadata({"rome_path": str(tmp_path)})


def test_completed_local_worker_is_replayed_without_subprocess(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(completed()))
    job = Job(tmp_path, {"result_path": str(path), "worker_pid": 123})
    async def no_launch(*args, **kwargs):
        pytest.fail("must replay persisted result")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_launch)
    assert asyncio.run(caesar.generate("Q", {}, job))["text"] == completed()["result"]["text"]


@pytest.mark.parametrize("reranking", [{}, {"enable_reranking": True}, {"enable_reranking": False}],
                         ids=["default", "enabled", "disabled"])
def test_launch_persists_pid_and_result_without_serializing_secrets(tmp_path, monkeypatch, reranking):
    job = Job(tmp_path)
    async def launch(*args, **kwargs):
        assert args[1:3] == ("-m", "crest.providers.caesar_worker")
        assert kwargs["start_new_session"] is True
        assert job.state["submission_unknown"] is True
        request = json.loads(Path(args[args.index("--request") + 1]).read_text())
        assert "api_key" not in json.dumps(request)
        assert "do-not-write-this" not in json.dumps(request)
        assert request["settings"] == reranking
        config = worker.build_config(request["prompt"], request["settings"],
                                     Path(request["output_dir"]), request["worker_id"])
        assert config["ChromaClientManager"]["enable_reranking"] is reranking.get("enable_reranking", True)
        Path(args[args.index("--result") + 1]).write_text(json.dumps(completed()))
        class Child:
            pid = 876
            returncode = 0
            async def wait(self): return 0
        return Child()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(caesar.generate("Q", {"api_key": "do-not-write-this", **reranking}, job))
    assert result["text"]
    assert job.state["worker_pid"] == 876
    assert job.state["submission_unknown"] is False


@pytest.mark.parametrize("backoff, expected_waits", [
    ({}, [1.25, 2.25, 4.25, 8.25, 16.25, 30.25, 30.25]),
    ({"retry_backoff_base_seconds": 3, "retry_backoff_max_seconds": 5},
     [3.25, 5.25, 5.25, 5.25, 5.25, 5.25, 5.25]),
    ({"retry_backoff_base_seconds": .5, "retry_backoff_max_seconds": 1.5},
     [.75, 1.25, 1.75, 1.75, 1.75, 1.75, 1.75]),
])
def test_worker_retries_honor_configured_backoff_through_adapter(tmp_path, monkeypatch, backoff, expected_waits):
    waits, sent = [], []
    class RateLimited(Exception):
        status_code = 429
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            if len(sent) < 8:
                raise RateLimited()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    class Agent(FakeAgent):
        shutdown_called = False
        def __init__(self, **kwargs): pass
        def explore(self):
            SDK().request(object, SimpleNamespace(json_data={
                "model": worker.SOL, "messages": [], "max_completion_tokens": 100}))
            return artifact()
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK):
            yield Agent
    async def launch(*args, **kwargs):
        request = json.loads(Path(args[args.index("--request") + 1]).read_text())
        assert worker.run_worker(request, Path(args[args.index("--result") + 1])) == 0
        class Child:
            pid = 876
            returncode = 0
            async def wait(self): return 0
        return Child()
    monkeypatch.setattr(worker, "_runtime", runtime)
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: .25)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    result = asyncio.run(caesar.generate("Q", {"retry_attempts": 8, **backoff}, Job(tmp_path)))

    assert result["text"]
    assert len(sent) == 8
    assert waits == expected_waits
    assert result["usage"]["failed_calls"] == 7
    assert result["usage"]["successful_calls"] == 1


@pytest.mark.parametrize("elapsed,finishes", [(8000, True), (worker.DEFAULT_TIMEOUT_SECONDS + 301, False)])
def test_resumed_live_worker_is_awaited_without_relaunch_until_the_worker_timeout(tmp_path, monkeypatch, elapsed, finishes):
    # Regression: the parent defaulted to 7200 s and killed workers still inside their own 21600 s deadline.
    path = tmp_path / "result.json"
    job = Job(tmp_path, {"result_path": str(path), "worker_pid": 876, "worker_started_at": time.time() - elapsed})
    terminated = []
    async def stop(state): terminated.append(state["worker_pid"])
    async def sleep(_): path.write_text(json.dumps(completed()))
    async def no_launch(*args, **kwargs): pytest.fail("duplicate worker")
    monkeypatch.setattr(caesar, "_worker_alive", lambda state: True)
    monkeypatch.setattr(caesar, "_terminate_worker", stop)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_launch)
    if finishes:
        assert asyncio.run(caesar.generate("Q", {}, job))["text"] and not terminated
    else:
        with pytest.raises(TimeoutError, match="21600 seconds"):
            asyncio.run(caesar.generate("Q", {}, job))
        assert terminated == [876]


@pytest.mark.parametrize("state", [{"submission_unknown": True}, {"worker_pid": 876, "worker_started_at": 1}])
def test_unknown_or_dead_worker_requires_review_instead_of_paid_retry(tmp_path, monkeypatch, state):
    job = Job(tmp_path, state)
    monkeypatch.setattr(caesar, "_worker_alive", lambda _: False)
    with pytest.raises(RuntimeError, match="(?i)(unknown|interrupted|review)"):
        asyncio.run(caesar.generate("Q", {}, job))


def test_worker_failure_and_timeout_are_not_success(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"status": "failed", "error": "Caesar failed", "usage": {"unknown_cost": True}}))
    job = Job(tmp_path, {"result_path": str(path)})
    with pytest.raises(RuntimeError, match="Caesar failed"):
        asyncio.run(caesar.generate("Q", {}, job))
    path.unlink()
    job = Job(tmp_path, {"result_path": str(path)})
    job.state.update(worker_pid=876, worker_started_at=1)
    monkeypatch.setattr(caesar, "_worker_alive", lambda _: True)
    terminated = []
    async def stop(state): terminated.append(state["worker_pid"])
    monkeypatch.setattr(caesar, "_terminate_worker", stop)
    with pytest.raises(TimeoutError):
        asyncio.run(caesar.generate("Q", {"timeout_seconds": 0}, job))
    assert terminated == [876]
    assert job.state["remote_status"] == "timed_out"
    assert job.state["raw"]["usage"]["unknown_cost"] is True


def test_worker_invokes_api_shuts_down_and_atomically_persists_result(tmp_path, monkeypatch):
    instances = []
    class Agent(FakeAgent):
        shutdown_called = False
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            instances.append(self)
        def explore(self): return artifact()
        def shutdown(self): self.shutdown_called = True
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    request = {"prompt": "Q", "settings": {}, "output_dir": str(tmp_path / "output"), "job_key": "abc"}
    result_path = tmp_path / "result.json"
    assert worker.run_worker(request, result_path) == 0
    assert json.loads(result_path.read_text())["status"] == "completed"
    assert instances[0].shutdown_called
    assert not list(tmp_path.glob("*.tmp"))


def test_scoped_compatibility_registers_prices_models_tokenizer_and_prompt_helpers_then_restores():
    class Handler:
        MODEL_PRICING = {"old": {"input": 1, "output": 2}}
        MODEL_CONTEXT_SIZE = {"old": 1}
        REASONING_MODELS = {"old"}
        _known_models_registered = True
    class Settings:
        _prompt_helper, _chat_prompt_helper = None, "preset"
        prompt_helper = property(lambda self: self._prompt_helper, lambda self, v: setattr(self, "_prompt_helper", v))
        chat_prompt_helper = property(lambda self: self._chat_prompt_helper, lambda self, v: setattr(self, "_chat_prompt_helper", v))
    config = {"LLMHandler": {"max_completion_tokens": 10000}}
    llama = SimpleNamespace(O1_MODELS={}, CHAT_MODELS={}, ALL_AVAILABLE_MODELS={})
    llm = SimpleNamespace(model_cost={}, register_model=lambda entries: None)
    registry, settings = {}, Settings()
    with worker.compatibility(Handler, config, llm, llama, 2000, tokenizer_registry=registry, llama_settings=settings,
                              prompt_helpers={"prompt_helper": "big", "chat_prompt_helper": "big-chat"}):
        assert registry["gpt-6.1-sol"] == "o200k_base"
        assert settings.prompt_helper == "big" and settings.chat_prompt_helper == "big-chat"
        assert llama.ALL_AVAILABLE_MODELS[worker.LUNA] == worker.KB_CONTEXT_WINDOW
        assert Handler.MODEL_PRICING["gpt-6.1-sol"] == {"input": 2, "output": 10}
        assert Handler.MODEL_CONTEXT_SIZE["gpt-6.1-sol"] == 1050000
        assert Handler.MODEL_PRICING["gpt-6-luna"] == {"input": .1, "output": .5}
        assert Handler.MODEL_CONTEXT_SIZE["gpt-6-luna"] == 1050000
        assert "gpt-6-luna" in Handler.REASONING_MODELS
        assert llama.O1_MODELS["gpt-6-luna"] == 1050000
        assert "gpt-6.1-sol" in Handler.REASONING_MODELS
        assert llama.O1_MODELS["gpt-6.1-sol"] == 1050000
        assert llama.CHAT_MODELS["gpt-6.1-sol"] == 1050000
        assert config["LLMHandler"]["max_completion_tokens"] == 2000
    assert "gpt-6.1-sol" not in Handler.MODEL_PRICING
    assert not llama.CHAT_MODELS and llama.ALL_AVAILABLE_MODELS == {}
    assert config["LLMHandler"]["max_completion_tokens"] == 10000
    assert registry == {}
    assert settings._prompt_helper is None and settings._chat_prompt_helper == "preset"


def test_sdk_audit_covers_chat_embeddings_and_failed_call_unknown_cost(tmp_path):
    class SDK:
        def request(self, cast_to, options, **kwargs):
            data = options.json_data
            if data.get("fail"): raise TimeoutError("transport timeout")
            if data["model"].startswith("text-embedding"):
                return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=50, total_tokens=50), model=data["model"])
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120), model=data["model"])
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    original = SDK.request
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "Q"}], "max_completion_tokens": 100}))
        SDK().request(object, SimpleNamespace(json_data={"model": "text-embedding-3-small", "input": ["source"]}))
        with pytest.raises(worker.SDKRequestFailed):
            SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "fail": True, "messages": [], "max_completion_tokens": 100}))
    assert SDK.request is original
    usage = json.loads((tmp_path / "usage.json").read_text())
    assert usage["input_tokens"] == 150
    assert usage["output_tokens"] == 20
    assert usage["successful_calls"] == 2
    assert usage["failed_calls"] == 1
    assert usage["known_cost_usd"] == pytest.approx(.000401)
    assert usage["unknown_cost"] is True
    assert usage["cost_usd"] is None


def test_budget_reservation_blocks_call_before_send_and_does_not_bill_it(tmp_path):
    class SDK:
        def request(self, *args, **kwargs): pytest.fail("overbudget request sent")
    audit = worker.UsageAudit(.001, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.BudgetExceeded):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 6000}))
    assert audit.snapshot()["successful_calls"] == 0
    assert audit.snapshot()["failed_calls"] == 0


def test_sdk_audit_observes_real_sdk_raw_response_and_async_embeddings(tmp_path):
    import httpx
    from openai import OpenAI, AsyncOpenAI
    from openai._base_client import SyncAPIClient, AsyncAPIClient

    def transport(request):
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"object": "list", "model": "text-embedding-3-small", "data": [{"object": "embedding", "index": 0, "embedding": [.1, .2]}], "usage": {"prompt_tokens": 50, "total_tokens": 50}})
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": "gpt-6.1-sol", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "complete"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SyncAPIClient, AsyncAPIClient):
        with OpenAI(api_key="offline-test", http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            result = client.chat.completions.with_raw_response.create(model="gpt-6.1-sol", messages=[{"role": "user", "content": "Q"}], max_completion_tokens=100)
            assert result.parse().choices[0].message.content == "complete"
        async def embed():
            async with AsyncOpenAI(api_key="offline-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                await client.embeddings.create(model="text-embedding-3-small", input=["source"], encoding_format="float")
        asyncio.run(embed())
    usage = audit.snapshot()
    assert usage["successful_calls"] == 2
    assert usage["cost_usd"] == pytest.approx(.000401)


def test_worker_failure_retains_partial_usage_and_still_shuts_down(tmp_path, monkeypatch):
    instances = []
    class Agent(FakeAgent):
        def __init__(self, **kwargs): instances.append(self)
        def explore(self): raise TimeoutError("request outcome unknown")
        def shutdown(self): self.closed = True
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    assert worker.run_worker({"prompt": "Q", "settings": {}, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 1
    saved = json.loads(path.read_text())
    assert saved["status"] == "failed"
    assert saved["usage"]["unknown_cost"] is True
    assert instances[0].closed


def test_cancellation_keeps_checkpoint_for_resuming_live_worker(tmp_path, monkeypatch):
    job = Job(tmp_path)
    async def launch(*args, **kwargs):
        class Child:
            pid = 876
            returncode = None
            async def wait(self): return 0
        return Child()
    async def sleep(_): raise asyncio.CancelledError
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(caesar.generate("Q", {}, job))
    assert job.state["worker_pid"] == 876
    assert job.state["submission_unknown"] is False
    assert job.state["remote_status"] == "running"


def test_sdk_audit_rejects_truncated_chat_output_but_keeps_billed_usage(tmp_path):
    class SDK:
        def request(self, cast_to, options, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20), choices=[SimpleNamespace(finish_reason="length")])
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(ValueError, match="incomplete"):
        SDK().request(object, _options())
    assert audit.snapshot()["cost_usd"] == pytest.approx(.0004)
    assert audit.snapshot()["successful_calls"] == 1


def test_worker_redacts_environment_credentials_from_error_and_logs(tmp_path, monkeypatch, caplog):
    import logging
    key = "offline-private-credential-value"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    class Agent(FakeAgent):
        def __init__(self, **kwargs): pass
        def explore(self):
            logging.getLogger("offline-worker").warning("SDK failed with %s", key)
            raise RuntimeError("SDK failed with " + key)
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    assert worker.run_worker({"prompt": "Q", "settings": {}, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 1
    assert key not in path.read_text()
    assert key not in caplog.text


def test_sdk_audit_preserves_full_reported_usage_and_unknown_helper_prices(tmp_path):
    class SDK:
        def request(self, cast_to, options, **kwargs):
            usage = {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}, "completion_tokens_details": {"reasoning_tokens": 12}}
            return SimpleNamespace(usage=usage, model="custom-helper")
    audit = worker.UsageAudit(5, tmp_path / "usage.json", enforce=False)  # Soft mode permits unpriced helpers.
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "custom-helper", "messages": [], "max_completion_tokens": 100}))
    saved = audit.snapshot()
    assert saved["cost_usd"] is None
    assert saved["unknown_cost"] is True
    assert saved["events"][0]["raw_usage"]["completion_tokens_details"]["reasoning_tokens"] == 12
    assert saved["events"][0]["response_model"] == "custom-helper"


def test_finished_result_does_not_hang_on_child_exit(tmp_path, monkeypatch):
    job = Job(tmp_path)
    stopped = []
    async def launch(*args, **kwargs):
        Path(args[args.index("--result") + 1]).write_text(json.dumps(completed()))
        class Child:
            pid = 876
            returncode = None
            async def wait(self): await asyncio.sleep(10)
        return Child()
    async def stop(state): stopped.append(state["worker_pid"])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(caesar, "_terminate_worker", stop)
    async def run():
        return await asyncio.wait_for(caesar.generate("Q", {"timeout_seconds": .02}, job), .1)
    assert asyncio.run(run())["text"]
    assert stopped == [876]


@ROME_WORKER
def test_real_rome_handler_and_llama_kb_offline_validation(tmp_path, monkeypatch):
    """Exercise installed LiteLLM validation and SDK payloads without network access."""
    import socket
    import httpx
    monkeypatch.setenv("OPENAI_API_KEY", "offline-regression-test")
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    sent = []
    import copy
    import litellm
    original_sol = copy.deepcopy(litellm.model_cost.get(worker.SOL))
    with worker._runtime({"rome_path": ROME}, audit):
        with monkeypatch.context() as local:
            import openai
            from rome.llm_handler import LLMHandler
            from llama_index.llms.openai import OpenAI as LlamaOpenAI
            from llama_index.core.base.llms.types import ChatMessage
            def no_network(*args, **kwargs): pytest.fail("real network access attempted")
            local.setattr(socket.socket, "connect", no_network)
            def transport(request):
                payload = json.loads(request.content)
                sent.append(payload)
                assert "top_p" not in payload
                if len(sent) == 1:
                    assert "temperature" not in payload
                return httpx.Response(200, json={"id": "offline-real-handler", "object": "chat.completion", "created": 0, "model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"artifact":"complete"}'}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
            original_init = openai.OpenAI.__init__
            def init(instance, *args, **kwargs):
                kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(transport))
                original_init(instance, *args, **kwargs)
            local.setattr(openai.OpenAI, "__init__", init)
            config = worker.build_config("Q", {}, tmp_path / "output", "offline")
            handler = LLMHandler(config=config["LLMHandler"])
            assert handler.top_p == 1.0  # The installed LiteLLM drop_params path filters this.
            assert handler.chat_completion("Q", response_format={"type": "json_object"}) == '{"artifact":"complete"}'
            assert handler.chat_completion("Q", override_config={"reasoning_effort": "xhigh"}) == '{"artifact":"complete"}'
            assert handler.chat_completion("Q", override_config={"model": "gpt-6-luna", "reasoning_effort": "low"}) == '{"artifact":"complete"}'
            llama = LlamaOpenAI(model="gpt-6-luna", api_key="offline-regression-test", max_tokens=2000, additional_kwargs={"reasoning_effort": "low"})
            assert llama.chat([ChatMessage(role="user", content="Q")]).message.content == '{"artifact":"complete"}'
    assert len(sent) == 4
    assert sent[0]["model"] == sent[1]["model"] == worker.SOL
    assert sent[0]["reasoning_effort"] == "medium"
    assert sent[1]["reasoning_effort"] == "xhigh"
    assert sent[2]["model"] == sent[3]["model"] == worker.LUNA
    assert sent[2]["reasoning_effort"] == sent[3]["reasoning_effort"] == "low"
    assert audit.snapshot()["successful_calls"] == 4
    assert litellm.model_cost.get(worker.SOL) == original_sol


@ROME_WORKER
def test_fatal_deadline_passes_actual_rome_synthesis_catch_and_cleans_up(tmp_path, monkeypatch):
    ArtifactSynthesizer = rome_class(tmp_path, "caesar.artifact_synthesis", "ArtifactSynthesizer")
    calls = []
    class Agent(FakeAgent):
        def __init__(self, **kwargs): pass
        def chat_completion(self, *args, **kwargs):
            time.sleep(.1)
            return '{"artifact":"late response"}'
        def parse_json_response(self, value): return json.loads(value)
        def explore(self):
            synthesizer = object.__new__(ArtifactSynthesizer)
            synthesizer.agent = self
            synthesizer._reasoning_floor = {}
            synthesizer.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: calls.append("caught"))
            synthesizer._llm_call("JSON", ["artifact"], retries=1)
            return artifact()
        def shutdown(self): calls.append("shutdown")
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    assert worker.run_worker({"prompt": "Q", "settings": {"timeout_seconds": .01}, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 1
    assert calls == ["shutdown"]
    saved = json.loads(path.read_text())
    assert saved["status"] == "failed"
    assert "Deadline" in saved["error"]


@pytest.mark.parametrize("model,usage,expected", [
    pytest.param(worker.SOL, {"prompt_tokens": 1000}, None, id="missing-output-tokens"),
    pytest.param(worker.SOL, {"completion_tokens": 100}, None, id="missing-input-tokens"),
    pytest.param(worker.SOL, {"prompt_tokens": 1000, "completion_tokens": 100,
                              "prompt_tokens_details": {"cache_write_tokens": 1000}}, .0035, id="sol-cache-write"),
    pytest.param(worker.SOL, {"prompt_tokens": 1000, "completion_tokens": 100,
                              "prompt_tokens_details": {"cached_tokens": 1000}}, .0011, id="sol-cache-read"),
    pytest.param(worker.SOL, {"prompt_tokens": 1000, "completion_tokens": 100,
                              "prompt_tokens_details": {"cached_tokens": 400, "cache_write_tokens": 200}}, .00234,
                 id="sol-cache-read-and-write"),
    pytest.param(worker.SOL, {"prompt_tokens": 1000, "completion_tokens": 100,
                              "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 200}}, None,
                 id="sol-invalid-cache-partition"),
    pytest.param(worker.SOL, {"prompt_tokens": 272001, "completion_tokens": 100}, 1.089504, id="sol-long-context"),
    pytest.param(worker.LUNA, {"prompt_tokens": 1000, "completion_tokens": 100,
                               "prompt_tokens_details": {"cache_write_tokens": 1000}}, .000175, id="luna-cache-write"),
    pytest.param(worker.LUNA, {"prompt_tokens": 272001, "completion_tokens": 100, "prompt_tokens_details": {}}, .0544752,
                 id="luna-long-context"),
])
def test_reported_chat_usage_prices_cache_and_long_context_or_stays_unknown(tmp_path, model, usage, expected):
    """Cache reads/writes partition reported input; long context reprices the whole request."""
    class SDK:
        def request(self, *args, **kwargs): return SimpleNamespace(usage=usage)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, _options(model))
    snapshot = audit.snapshot()
    if expected is None:
        assert snapshot["cost_usd"] is None and snapshot["unknown_cost"] is True
    else:
        assert snapshot["cost_usd"] == pytest.approx(expected)


@pytest.mark.parametrize("reserve,expected_status,page_calls,synthesis_fails", [(1.5, "completed", 3, False), (4., "failed", 0, False), (1.5, "failed", 3, True)])
def test_exploration_reserve_leaves_budget_for_real_synthesis_and_rejects_no_insights(tmp_path, monkeypatch, reserve, expected_status, page_calls, synthesis_fails):
    calls = []
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 0, "completion_tokens": 1})
    def pay(label):
        calls.append(label)
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 1}))
    class Agent(FakeAgent):
        def __init__(self, **kwargs):
            self.current_iteration = 0
            self.pages = 0
            self.synthesizer = SimpleNamespace(synthesize_artifact=self.synthesize)
        def perceive(self):
            if getattr(self, "synthesis_probe", False): return "content", []
            pay("page")
            self.pages += 1
            return "content", []
        def explore(self):
            for iteration in range(1, 31):
                self.current_iteration = iteration
                self.perceive()
            return self.synthesize()
        def synthesize(self):
            self.synthesis_probe = True
            assert self.perceive() == ("content", [])
            if not self.pages:
                return artifact(num_drafts=0)
            if synthesis_fails:
                raise RuntimeError("synthesis unavailable")
            pay("synthesis")
            return artifact(metadata={"synthesis_queries": 15, "iterations_run": self.current_iteration})
        def shutdown(self): calls.append("shutdown")
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    settings = {"budget_usd": 4., "synthesis_reserve_usd": reserve, "model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 1000000}}}
    worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path)
    saved = json.loads(path.read_text())
    assert saved["status"] == expected_status
    assert calls.count("page") == page_calls
    assert calls[-1] == "shutdown"
    if expected_status == "failed":
        assert saved["raw"]["exploration_budget_stop"]["iterations_completed"] == page_calls
    if expected_status == "completed":
        assert calls.count("synthesis") == 1
        result = saved["result"]
        assert result["cost_usd"] == 4.
        assert result["raw"]["artifact"]["metadata"]["iterations_run"] == page_calls
        assert result["raw"]["exploration_budget_stop"]["iterations_completed"] == page_calls
        assert any("exploration" in warning.lower() and "reserve" in warning.lower() for warning in result["warnings"])


@pytest.mark.parametrize("status,budget,wait", [(520, .003, 60), (429, .002, 3)], ids=["http520-body", "confirmed-429"])
def test_real_sdk_retry_waits_server_delay_and_bills_only_possibly_paid_attempts(tmp_path, monkeypatch, status, budget, wait):
    """A 520 may have been billed, so its reservation is retained; a confirmed 429 is never double billed."""
    import httpx
    sent, waits = [], []
    def transport(request):
        sent.append(request)
        if len(sent) > 1:
            return _sdk_chat_reply()
        if status == 520:
            return httpx.Response(520, json={"title": "Unknown origin error", "status": 520, "retryable": True, "retry_after": 60})
        return httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"message": "try later", "code": "rate_limit_exceeded", "type": "rate_limit_error"}})
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    audit = worker.UsageAudit(budget, tmp_path / "usage.json")
    assert _real_sdk_chat(audit, transport, False).choices[0].message.content == "answer"
    usage = audit.snapshot()
    assert len(sent) == 2
    assert waits == [wait]
    assert usage["successful_calls"] == 1
    assert usage["failed_calls"] == 1
    if status == 520:
        assert usage["unknown_cost"] is True
        assert usage["cost_usd"] is None
        assert usage["events"][0]["reserved_usd"] > 0
        assert usage["known_cost_usd"] + usage["events"][0]["reserved_usd"] <= budget
    else:
        assert usage["rate_limit_events"] == 1
        assert usage["unknown_cost"] is False
        assert usage["cost_usd"] == pytest.approx(.0004)
        assert usage["events"][0]["reserved_usd"] == 0
        assert usage["events"][0]["cost_usd"] == 0


class RateLimited(Exception):
    status_code = 429
    response = SimpleNamespace(headers={"Retry-After": "2"})


@pytest.mark.parametrize("error,budget,wait", [(Transient, .003, 60), (RateLimited, .002, 2)], ids=["http520-body", "confirmed-429"])
def test_async_sdk_retry_keeps_both_attempts_and_server_delay(tmp_path, monkeypatch, error, budget, wait):
    attempts, waits = [], []
    class Sync:
        def request(self, *args, **kwargs): pytest.fail("sync request")
    class Async:
        async def request(self, *args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1: raise error()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    async def sleep(delay): waits.append(delay)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    audit = worker.UsageAudit(budget, tmp_path / "usage.json")
    with audit.installed(Sync, Async):
        asyncio.run(Async().request(object, _options()))
    assert len(attempts) == 2
    assert waits == [wait]
    if error is Transient:
        assert audit.snapshot()["unknown_cost"] is True
    else:
        assert audit.snapshot()["rate_limit_events"] == 1
        assert audit.snapshot()["cost_usd"] == pytest.approx(.0004)


def test_transient_retry_is_blocked_when_second_reservation_cannot_fit(tmp_path, monkeypatch):
    sent = []
    SDK = _failing_sdk(sent)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    audit = worker.UsageAudit(.002, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.BudgetExceeded):
        SDK().request(object, _options())
    assert len(sent) == 1
    assert audit.snapshot()["events"][0]["reserved_usd"] > 0
    assert audit.snapshot()["unknown_cost"] is True


def test_explicit_nonretryable_520_is_not_repeated(tmp_path, monkeypatch):
    class Final(Transient):
        body = {"retryable": False, "retry_after": 60}
    sent = []
    SDK = _failing_sdk(sent, Final)
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("must not sleep"))
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options())
    assert len(sent) == 1


def test_retry_after_wait_never_extends_worker_wall_deadline(tmp_path):
    sent = []
    SDK = _failing_sdk(sent)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with worker._deadline(.02), audit.installed(SDK), pytest.raises(worker.WorkerDeadlineExceeded):
        SDK().request(object, _options())
    assert len(sent) == 1


def test_four_520_attempts_hold_four_reservations_and_never_enter_outer_retry(tmp_path, monkeypatch):
    sent, waits = [], []
    SDK = _failing_sdk(sent)
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    audit = worker.UsageAudit(.01, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options())
    assert len(sent) == 4
    assert waits == [60, 60, 60]
    value = audit.snapshot()
    assert value["failed_calls"] == 4
    assert len(value["events"]) == 4
    assert sum(event["reserved_usd"] for event in value["events"]) <= .01
    assert all(event["unknown_cost"] for event in value["events"])


def test_unpriced_model_failure_is_never_retried_in_soft_mode(tmp_path, monkeypatch):
    # Hard mode refuses the unpriced model before dispatch: test_hard_sdk_audit_rejects_unpriced_invalid_price_or_unbounded_dispatch.
    sent = []
    SDK = _failing_sdk(sent)
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("unbounded retry"))
    audit = worker.UsageAudit(5, tmp_path / "usage.json", enforce=False)
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options("unpriced-helper"))
    assert len(sent) == 1
    assert not audit.pending
    assert len(audit.events) == 1
    assert audit.events[0]["unknown_cost"] is True
    assert audit.events[0]["cost_usd"] is None


@pytest.mark.parametrize("status,expected_attempts", [(401, 1), (429, 4)])
def test_sdk_permanent_auth_and_exhausted_rejections_do_not_retry_outside_boundary(tmp_path, monkeypatch, status, expected_attempts):
    attempts = []
    class Rejected(Exception):
        status_code = status
        response = SimpleNamespace(headers={"Retry-After": "0"})
    class SDK:
        def request(self, *args, **kwargs):
            attempts.append(1)
            raise Rejected("rejected")
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options())
    assert len(attempts) == expected_attempts
    assert audit.snapshot()["cost_usd"] == 0
    assert audit.snapshot()["unknown_cost"] is False


def test_unparseable_paid_response_retains_unknown_cost_reservation(tmp_path):
    attempts = []
    class BadResponse:
        def parse(self): raise ValueError("unparseable response")
    class SDK:
        def request(self, *args, **kwargs):
            attempts.append(1)
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20}) if len(attempts) == 1 else BadResponse()
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    options = _options()
    with audit.installed(SDK):
        SDK().request(object, options)
        with pytest.raises(worker.SDKRequestFailed): SDK().request(object, options)
    assert audit.snapshot()["cost_usd"] is None
    assert audit.snapshot()["unknown_cost"] is True
    assert audit.snapshot()["in_flight"]


@ROME_WORKER
def test_bad_accepted_response_cannot_reenter_actual_rome_paid_retry_loop(tmp_path):
    ArtifactSynthesizer = rome_class(tmp_path, "caesar.artifact_synthesis", "ArtifactSynthesizer")
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    paid = []
    class BadResponse:
        def parse(self): raise ValueError("accepted response could not be decoded")
    class SDK:
        def request(self, *args, **kwargs):
            paid.append(1)
            if len(paid) == 1: return BadResponse()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20}, text='{"artifact":"complete"}')
    options = _options()
    synthesizer = object.__new__(ArtifactSynthesizer)
    synthesizer.agent = SimpleNamespace(chat_completion=lambda *a, **kw: SDK().request(object, options).text, parse_json_response=json.loads)
    synthesizer._reasoning_floor = {}
    synthesizer.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None)
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        synthesizer._llm_call("JSON", ["artifact"], retries=2)
    assert len(paid) == 1
    assert audit.snapshot()["cost_usd"] is None
    assert len(audit.snapshot()["in_flight"]) == 1


def test_completed_caesar_rate_limits_prevent_adaptive_growth_and_replays_deduplicate(tmp_path):
    from crest.concurrency import AdaptiveLimiter
    async def run():
        controller = AdaptiveLimiter(maximum=4, initial=1)
        jobs = []
        for name in ("one", "two"):
            job = Job(tmp_path / name)
            path = job.directory / "result.json"
            record = completed()
            record["result"]["usage"]["rate_limit_events"] = 1
            path.write_text(json.dumps(record))
            job.state["result_path"] = str(path)
            job.rate_controller = controller
            jobs.append(job)
            await caesar.generate("Q", {}, job)
            await controller.succeeded()
        assert controller.snapshot()["current"] == 1
        assert controller.snapshot()["rate_limit_events"] == 2
        for job in jobs:
            await caesar.generate("Q", {}, job)
        assert controller.snapshot()["rate_limit_events"] == 2
    asyncio.run(run())


def test_live_worker_rate_event_is_forwarded_once_before_final_result(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    job = Job(tmp_path, {"result_path": str(path), "worker_pid": 876, "worker_started_at": time.time()})
    delays = []
    async def limited(delay): delays.append(delay)
    job.rate_controller = SimpleNamespace(rate_limited=limited)
    usage = {"rate_limit_events": 1, "events": [{"status_code": 429, "retry_after_seconds": 3}]}
    output_dir = tmp_path / "caesar-output"
    output_dir.mkdir()
    (output_dir / "usage.json").write_text(json.dumps(usage))
    monkeypatch.setattr(caesar, "_worker_alive", lambda state: True)
    async def sleep(_):
        assert delays == [3]
        record = completed()
        record["result"]["usage"].update(usage)
        path.write_text(json.dumps(record))
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert asyncio.run(caesar.generate("Q", {}, job))["text"]
    assert delays == [3]


def test_async_accepted_response_parse_failure_is_fatal_without_retry(tmp_path):
    paid = []
    class Sync:
        def request(self, *args, **kwargs): pytest.fail("sync request")
    class BadResponse:
        async def parse(self): raise ValueError("accepted async response could not be decoded")
    class Async:
        async def request(self, *args, **kwargs):
            paid.append(1)
            return BadResponse()
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(Sync, Async), pytest.raises(worker.SDKRequestFailed):
        asyncio.run(Async().request(object, _options()))
    assert len(paid) == 1
    assert audit.snapshot()["cost_usd"] is None
    assert len(audit.snapshot()["in_flight"]) == 1


@ROME_WORKER
def test_chroma_start_uses_worker_interpreter_without_chroma_on_path(tmp_path, monkeypatch):
    """Exercise Rome's real startup lifecycle with a local fake Chroma CLI."""
    import atexit
    import socket
    import sys
    ChromaServerManager = rome_class(tmp_path, "rome.kb_server", "ChromaServerManager")
    # Rome polls readiness with time.sleep(1); poll every 20 ms instead, with the same 5 s overall bound.
    real_sleep = time.sleep
    monkeypatch.setattr(sys.modules[ChromaServerManager.__module__], "time",
                        SimpleNamespace(sleep=lambda seconds: real_sleep(min(seconds, .02))))
    package = tmp_path / "fake-modules" / "chromadb"
    (package / "cli").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli" / "__init__.py").write_text("")
    (package / "cli" / "cli.py").write_text('''import json, sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

def app():
    args = sys.argv
    host, port = args[args.index("--host") + 1], int(args[args.index("--port") + 1])
    persist = Path(args[args.index("--path") + 1])
    (persist.parent / "cli-argv.json").write_text(json.dumps({"executable": sys.executable, "argv": args}))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        def log_message(self, *args): pass
    HTTPServer((host, port), Handler).serve_forever()
''')
    monkeypatch.setenv("PATH", str(tmp_path / "no-executables"))
    monkeypatch.setenv("PYTHONPATH", str(package.parent))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    manager = ChromaServerManager({"host": "127.0.0.1", "port": port,
        "persist_path": str(tmp_path / "store"), "startup_timeout": 250, "shutdown_timeout": 1})
    original = ChromaServerManager._try_start_command
    with worker.chroma_python_cli(ChromaServerManager):
        try:
            assert manager.start()
            saved = json.loads((tmp_path / "cli-argv.json").read_text())
            assert saved["executable"] == sys.executable
            assert saved["argv"][:2] == ["chroma", "run"]
            assert saved["argv"][saved["argv"].index("--port") + 1] == str(port)
        finally:
            manager._kill_process()
            atexit.unregister(manager.stop)
    assert ChromaServerManager._try_start_command is original


@ROME_WORKER
def test_parallel_quick_exploration_reserves_synthesis_budget_and_ingests_completed_pages(tmp_path, monkeypatch):
    """Run Rome's quick loop, including its real executor and result ingestion."""
    import threading
    import networkx as nx
    CaesarAgent = rome_class(tmp_path, "caesar.caesar_agent", "CaesarAgent")
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    observed = {"active": 0, "peak": 0, "pages": 0}
    calls = []
    class SDK:
        def request(self, cast_to, options, **kwargs):
            label = options.json_data["label"]
            with lock:
                observed["active"] += 1
                observed["peak"] = max(observed["peak"], observed["active"])
                calls.append(label)
                if label == "page": observed["pages"] += 1
                page_number = observed["pages"]
            try:
                if label == "page" and page_number <= 2:
                    barrier.wait(timeout=3)
                return SimpleNamespace(usage={"prompt_tokens": 0, "completion_tokens": 1})
            finally:
                with lock: observed["active"] -= 1
    def pay(label):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 1, "label": label}))
    class Agent(FakeAgent):
        use_quick_explore = True
        shutdown_called = False
        def __init__(self, **kwargs):
            self.current_iteration = 0
            self.max_iterations = kwargs["config"]["CaesarAgent"]["max_iterations"]
            self.quick_explore_workers = kwargs["config"]["CaesarAgent"]["quick_explore_workers"]
            self.visited_urls, self.failed_urls = {}, set()
            self.starting_url = "https://seed.test"
            self.graph = nx.DiGraph()
            self.logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None,
                                          warning=lambda *args: None)
            self.checkpoint_manager = SimpleNamespace(save=lambda *args, **kwargs: None)
            self.kb_manager = SimpleNamespace(
                add_texts=self.ingest,
                collection=SimpleNamespace(get=lambda *, ids, include: {
                    "ids": [], "documents": [], "metadatas": []}),
            )
            self.synthesizer = SimpleNamespace(synthesize_artifact=self.synthesize)
        def perceive(self):
            return "seed", [(f"https://page.test/{i}", "page") for i in range(250)]
        def _quick_perceive_and_think(self, url, iteration):
            pay("page")
            # Rome deduplicates notes by content, so these two pages need distinct insights.
            return {"url": url, "insights": f"insight from {url}", "iteration": iteration}
        def explore(self): return CaesarAgent.quick_explore(self)
        def ingest(self, texts):
            assert observed["active"] == 0
            assert len(texts) == 2
            pay("embedding")
        def synthesize(self):
            pay("synthesis")
            return artifact(metadata={"synthesis_queries": 15, "iterations_run": self.current_iteration})
        def shutdown(self): self.shutdown_called = True
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    settings = {"synthesis_reserve_usd": 3., "budget_usd": 5., "model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 1000000}}}
    assert worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 0
    result = json.loads(path.read_text())["result"]
    assert calls.count("page") == 2
    assert calls.count("embedding") == 1
    assert calls.count("synthesis") == 1
    assert observed["peak"] == 2
    assert result["cost_usd"] == 4
    assert result["usage"]["in_flight"] == []
    assert result["raw"]["exploration_budget_stop"]["iterations_completed"] == 2


def test_reduced_qa_rounds_preserve_complete_artifact_and_actual_metadata():
    value = artifact(metadata={"synthesis_queries": 4})
    result = worker.extract_result(value, "gpt-6.1-sol", {})
    assert result["text"]
    assert result["raw"]["artifact"]["metadata"]["synthesis_queries"] == 4
    assert any("4" in warning and "15" in warning for warning in result["warnings"])


@ROME_WORKER
def test_adaptive_qa_budget_finishes_three_drafts_and_merge(tmp_path, monkeypatch):
    ArtifactSynthesizer = rome_class(tmp_path, "caesar.artifact_synthesis", "ArtifactSynthesizer")
    calls = []
    class SDK:
        def request(self, cast_to, options, **kwargs):
            calls.append(options.json_data["label"])
            return SimpleNamespace(usage={"prompt_tokens": 0, "completion_tokens": options.json_data["max_completion_tokens"]})
    def pay(label, tokens):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": tokens, "label": label}))
    class Synthesizer(ArtifactSynthesizer):
        synthesis_iterations = 15
        synthesis_drafts = 3
        synthesis_merge_artifacts = True
        def __init__(self):
            self._reasoning_floor = {}
            self._num_drafts = 3
            self.synthesis_top_k, self.synthesis_top_n = 8, 8
            self.filters = None
            self.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None)
            self.kb_manager = SimpleNamespace(query=self.query)
        def query(self, *args, **kwargs):
            try: pay("qa", 1)
            except worker.BudgetExceeded: return None, []
            return "answer", []
        def _generate_qa_pairs(self, *args, **kwargs):
            return ArtifactSynthesizer._generate_qa_pairs(self, "iterative (n=15)", "question")
        def _merge_artifacts(self, drafts):
            pay("merge", 5)
            return artifact(metadata={"synthesis_queries": len(drafts[-1])})
        def synthesize_artifact(self):
            drafts = []
            for index in range(1, 4):
                self._current_draft = index
                pairs = self._generate_qa_pairs()
                assert pairs
                pay("draft", 3)
                drafts.append(pairs)
                if index < 3: pay("refine", 1)
            return self._merge_artifacts(drafts)
    class Agent(FakeAgent):
        starting_query = "question"
        def __init__(self, **kwargs):
            self.synthesizer = Synthesizer()
            self.synthesizer.agent = self
        def chat_completion(self, *args, **kwargs):
            pay("next_query", 1)
            return '{"query":"next question"}'
        def parse_json_response(self, value): return json.loads(value)
        def explore(self):
            pay("exploration", 100)
            return self.synthesizer.synthesize_artifact()
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    # One output token costs $0.01: exploration $1.00, a Q&A round $0.02, a draft $0.03, a refinement $0.01,
    # the merge $0.05. A $1.60 ceiling leaves $0.60 for synthesis, so every draft is cut short yet all three
    # drafts and the merge still fit after the held-back write money.
    settings = {"budget_usd": 1.6, "max_completion_tokens": 5, "query_max_completion_tokens": 1,
                "synthesis_reasoning_effort": "medium",
                "model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 10000}}}
    assert worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 0
    result = json.loads(path.read_text())["result"]
    assert calls.count("draft") == 3
    assert calls.count("merge") == 1
    assert result["cost_usd"] <= 1.6
    records = result["raw"]["synthesis_budget"]["drafts"]
    assert len(records) == 3
    assert all(1 <= row["completed_qa_rounds"] <= 15 for row in records)
    assert any(row["completed_qa_rounds"] < 15 for row in records)
    assert any(row["budget_limited"] for row in records)
    assert result["raw"]["synthesis_budget"]["merge_completed"] is True


def recovery_source(tmp_path, *, worker_id="original-worker", known_cost=.45898205, unknown_reserved=.2114525, budget=5):
    import networkx as nx
    source = tmp_path / "old-job"
    output = source / "caesar-output"
    (output / "__rome__").mkdir(parents=True)
    (output / "chroma").mkdir()
    (output / "chroma" / "chroma.sqlite3").write_bytes(b"copied database")
    (output / "chroma" / "chroma.sqlite3-wal").write_bytes(b"preserved WAL")
    graph = nx.DiGraph()
    graph.add_node("https://seed.test", insights="saved knowledge")
    checkpoint = {"iteration": 2, "role": "Your role: saved role", "current_url": "https://seed.test", "url_stack": ["https://seed.test"],
        "visited_urls": {"https://seed.test": 1}, "web_searches_used": 12, "reseeds_used": 0,
        "traversal_history": [], "graph": nx.node_link_data(graph, edges="edges"),
        "config": {"starting_query": "Q", "starting_url": "https://seed.test", "allowed_domains": ["*"]},
        "cost": {"accumulated_cost": .44, "call_count": 19, "sessions": []}}
    worker.atomic_json(output / "__rome__" / "agent_old.checkpoint.json", checkpoint)
    worker.atomic_json(source / "caesar-request.json", {"prompt": "Q", "worker_id": worker_id, "job_key": "original-job", "settings": {"budget_usd": budget}})
    worker.atomic_json(source / "caesar-result.json", {"status": "failed", "error": "ambiguous timeout", "usage": {"known_cost_usd": known_cost, "unknown_cost": True, "budget_target_usd": budget,
        "events": [{"status": "failed", "unknown_cost": True, "reserved_usd": unknown_reserved}], "in_flight": []}})
    return source


@ROME_WORKER
def test_explicit_recovery_copies_store_and_uses_rome_checkpoint_without_exploration(tmp_path, monkeypatch):
    CheckpointManager = rome_class(tmp_path, "caesar.checkpoint", "CheckpointManager")
    import networkx as nx
    source = recovery_source(tmp_path)
    original = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    instances = []
    class Agent(FakeAgent):
        def __init__(self, name, repository, config):
            instances.append(self)
            self.repository, self.name, self.config = repository, name, config
            self.starting_query, self.starting_url = "Q", config["CaesarAgent"]["starting_url"]
            self.allowed_domains = ["*"]
            self.current_iteration, self.web_searches_used, self.reseeds_used = 0, 0, 0
            self.traversal_history, self.visited_urls, self.url_stack = [], {}, [self.starting_url]
            self.current_depth, self.current_url = 1, self.starting_url
            self.graph, self.role, self.load_saved_role = nx.DiGraph(), "default role", True
            self.llm_handler = SimpleNamespace(accumulated_cost=0, call_count=0)
            self.kb_manager = SimpleNamespace(size=lambda: 1)
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: artifact())
            assert config["CaesarAgent"]["max_iterations"] == 0
            assert config["CaesarAgent"]["adapt_role"] is False
            assert config["LLMHandler"]["cost_limit"] == 4.3
            assert CheckpointManager(self).load()
            assert self.role == "Your role: saved role"
            assert self.current_iteration == 2
            assert self.llm_handler.accumulated_cost == 0
            assert Path(repository, "chroma", "chroma.sqlite3-wal").read_bytes() == b"preserved WAL"
        def get_log_dir(self): return str(Path(self.repository) / "__rome__")
        def get_id(self): return "agent_" + self.name
        def explore(self): pytest.fail("recovery must not perform exploration")
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "new-job" / "result.json"
    request = {"prompt": "Q", "settings": {"recovery_from": str(source), "budget_usd": 4.3}, "output_dir": str(path.parent / "output"), "job_key": "new-job"}
    assert worker.run_worker(request, path) == 0
    result = json.loads(path.read_text())["result"]
    assert instances
    assert result["raw"]["recovery"]["previous_known_cost_usd"] == .45898205
    assert result["raw"]["recovery"]["previous_unknown_reserved_usd"] == .2114525
    assert result["raw"]["recovery"]["budgeted_total_exposure_usd"] == pytest.approx(4.97043455)
    assert result["cost_usd"] is None
    assert original == {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}


@pytest.mark.parametrize("prompt,budget", [("wrong question", 4.3), ("Q", 5)])
def test_recovery_rejects_wrong_question_or_excess_new_budget(tmp_path, prompt, budget):
    source = recovery_source(tmp_path)
    config = worker.build_config(prompt, {}, tmp_path / "new-output", "new-id")
    with pytest.raises(ValueError):
        worker.prepare_synthesis_recovery(prompt, {"recovery_from": str(source), "budget_usd": budget}, tmp_path / "new-output", "new-key", config)


@pytest.mark.parametrize("configured_budget,expected_budget", [(None, 5.), (4., 4.), (6., 6.)])
def test_soft_recovery_preserves_over_target_history_and_accepts_positive_budget(tmp_path, configured_budget, expected_budget):
    source = recovery_source(tmp_path, known_cost=4.2, unknown_reserved=.3, budget=4.)
    original = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    settings = {"recovery_from": str(source), "budget_cap": "soft"}
    if configured_budget is not None:
        settings["budget_usd"] = configured_budget
    output = tmp_path / "new-output"
    config = worker.build_config("Q", settings, output, "new-worker")

    recovery = worker.prepare_synthesis_recovery("Q", settings, output, "new-key", config)

    assert recovery["original_budget_usd"] == 4.
    assert recovery["previous_known_cost_usd"] == 4.2
    assert recovery["previous_unknown_reserved_usd"] == .3
    assert recovery["previous_cost_unknown"] is True
    assert recovery["new_attempt_budget_usd"] == expected_budget
    assert recovery["budgeted_total_exposure_usd"] == pytest.approx(4.5 + expected_budget)
    assert config["LLMHandler"]["cost_limit"] == 0.
    assert json.loads((output / "recovery.json").read_text()) == recovery
    assert original == {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}


@pytest.mark.parametrize("cap", ["soft", "hard", "auto"])
@pytest.mark.parametrize("budget", [0., -1., float("nan"), float("inf"), -float("inf"), True, "4", None])
def test_recovery_requires_positive_finite_budget(tmp_path, cap, budget):
    source = recovery_source(tmp_path)
    settings = {"recovery_from": str(source), "budget_cap": cap, "budget_usd": budget}
    output = tmp_path / "new-output"
    config = worker.build_config("Q", settings, output, "new-worker")
    with pytest.raises(ValueError):
        worker.prepare_synthesis_recovery("Q", settings, output, "new-key", config)
    assert not output.exists()


@pytest.mark.parametrize("cap", ["hard", "auto"])
@pytest.mark.parametrize("original_budget,known,reserved,budget", [
    (10., .5, .25, 4.4),  # Within the residual, but above the recovery ceiling.
    (4., 3.5, .25, .3),  # Below the ceiling, but above the residual.
    (4., 4.2, .3, .1),   # No residual remains.
])
def test_hard_recovery_enforces_ceiling_and_residual(tmp_path, cap, original_budget, known, reserved, budget):
    source = recovery_source(tmp_path, known_cost=known, unknown_reserved=reserved, budget=original_budget)
    settings = {"recovery_from": str(source), "budget_cap": cap, "budget_usd": budget}
    output = tmp_path / "new-output"
    config = worker.build_config("Q", settings, output, "new-worker")
    with pytest.raises(ValueError):
        worker.prepare_synthesis_recovery("Q", settings, output, "new-key", config)
    assert not output.exists()


@pytest.mark.parametrize("prior_collection", [None, "inherited-collection"])
def test_recovery_uses_fresh_source_collection_unless_prior_recovery_names_one(tmp_path, prior_collection):
    ancestor = recovery_source(tmp_path / "ancestor")
    source = recovery_source(tmp_path / "fresh", worker_id="fresh-worker")
    request = json.loads((source / "caesar-request.json").read_text())
    mode = "recovery" if prior_collection else "budget_history"
    request["settings"][mode + "_from"] = str(ancestor)
    worker.atomic_json(source / "caesar-request.json", request)
    record = json.loads((source / "caesar-result.json").read_text())
    record["raw"] = {mode: {"source_job": str(ancestor)}}
    if prior_collection:
        record["raw"][mode]["collection_name"] = prior_collection
    worker.atomic_json(source / "caesar-result.json", record)
    settings = {"recovery_from": str(source), "budget_usd": 1.}
    output = tmp_path / "new-output"
    config = worker.build_config("Q", settings, output, "new-worker")

    recovery = worker.prepare_synthesis_recovery("Q", settings, output, "new-key", config)

    expected = prior_collection or "crest_2855a11d3596c48623a62d636f6b524fb7c0f71f"
    assert recovery["collection_name"] == expected
    assert config["ChromaClientManager"]["collection_name"] == expected
    assert len(recovery["ancestry"]) == 2
    assert recovery["previous_known_cost_usd"] == pytest.approx(.9179641)
    assert recovery["previous_unknown_reserved_usd"] == pytest.approx(.422905)
    assert (output / "chroma" / "chroma.sqlite3-wal").read_bytes() == b"preserved WAL"


@ROME_WORKER
@pytest.mark.parametrize("timeout,expected", [(None, 1200), (600, 600), (37, 37)])
def test_runtime_timeout_reaches_sdk_even_when_library_supplies_shorter_value(tmp_path, timeout, expected):
    import openai
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    settings = {"rome_path": ROME}
    if timeout is not None:
        settings["call_timeout_seconds"] = timeout
    with worker._runtime(settings, audit):
        with openai.OpenAI(api_key="offline", timeout=1) as client:
            assert client.timeout == expected
            assert client.with_options(timeout=1).timeout == expected
        async def check_async():
            async with openai.AsyncOpenAI(api_key="offline", timeout=1) as client:
                assert client.timeout == expected
                assert client.with_options(timeout=1).timeout == expected
        asyncio.run(check_async())


def test_recovery_source_content_is_part_of_cache_identity(tmp_path):
    source = recovery_source(tmp_path)
    settings = {"rome_path": str(tmp_path), "recovery_from": str(source)}
    old = caesar.identity_metadata(settings)
    (source / "caesar-output" / "chroma" / "chroma.sqlite3-wal").write_bytes(b"different saved insights")
    assert old != caesar.identity_metadata(settings)


def test_recovery_cannot_overwrite_its_original_job(tmp_path):
    source = recovery_source(tmp_path)
    original = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    with pytest.raises(ValueError):
        worker.run_worker({"prompt": "Q", "settings": {"recovery_from": str(source), "budget_usd": 4.3},
            "output_dir": str(source / "caesar-output"), "job_key": "new-job"}, tmp_path / "new-result.json")
    assert original == {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}


@ROME_WORKER
def test_runtime_packs_a_knowledge_base_query_into_one_call(tmp_path, monkeypatch):
    """llama-index-core 0.14.23 would otherwise use a 3,900-token window and split 20 chunks into 5 calls."""
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")  # construction only; nothing is sent
    audit = worker.UsageAudit(1, tmp_path / "usage.json")
    with worker._runtime({"rome_path": ROME}, audit):
        from llama_index.core import Settings
        from llama_index.core.prompts import PromptTemplate
        from llama_index.core.response_synthesizers import get_response_synthesizer
        from llama_index.llms.openai import OpenAI
        synthesizer = get_response_synthesizer(response_mode="compact", llm=OpenAI(model=worker.LUNA, max_tokens=2000))
        helper = synthesizer._prompt_helper
        assert helper.context_window == worker.KB_CONTEXT_WINDOW and helper.num_output == 2000
        template = PromptTemplate("Context:\n{context_str}\nQuestion: {query_str}\nAnswer:")
        assert len(helper.repack(template, ["word " * 700] * 20)) == 1
    assert Settings._prompt_helper is None and Settings._chat_prompt_helper is None


def test_soft_budget_cap_records_but_never_refuses(tmp_path):
    settings = {"budget_cap": "soft", "budget_usd": 1.0}
    assert worker.build_config("Q", settings, tmp_path, "w")["LLMHandler"]["cost_limit"] == 0.0
    assert worker.build_config("Q", {"budget_usd": 1.0}, tmp_path, "w")["LLMHandler"]["cost_limit"] == 1.0
    audit = worker.UsageAudit(1.0, tmp_path / "usage.json", enforce=False)
    audit.events.append({"status": "completed", "cost_usd": 5.0, "model": "gpt-6.1-sol"})
    token = audit.before(SimpleNamespace(json_data={"model": worker.SOL, "messages": [], "max_completion_tokens": 100}))
    assert token in audit.pending and audit.snapshot()["budget_exceeded"] is True
    class Agent:
        use_quick_explore = False
        def perceive(self): raise AssertionError("perceive must not be wrapped under a soft cap")
        def explore(self): return {"artifact": "Complete draft"}
    artifact, stop = worker._explore_with_synthesis_reserve(Agent(), settings, audit)
    assert artifact == {"artifact": "Complete draft"} and stop is None
    class Synthesizer:
        synthesis_drafts, synthesis_iterations, synthesis_merge_artifacts = 3, 20, True
        def _generate_qa_pairs(self): return [("Q", "A", [])]
    synthesizer = Synthesizer()
    with worker.adaptive_synthesis_budget(SimpleNamespace(synthesizer=synthesizer), settings, audit) as records:
        assert synthesizer._generate_qa_pairs() == [("Q", "A", [])] and audit.request_limit is None
    row = records["drafts"][0]  # Recorded for the report, never limited.
    assert records["enforced"] is False and row["budget_limited"] is False and row["qa_allowance_usd"] is None


@ROME_WORKER
def test_soft_budget_passes_real_rome_config_validation_and_disables_cost_checks(tmp_path, monkeypatch):
    from crest.config import load_config
    monkeypatch.setenv("OPENAI_API_KEY", "offline-soft-budget-test")
    settings = load_config()["research"]["caesar"]
    settings["budget_cap"] = "soft"
    audit = worker.UsageAudit(settings["budget_usd"], tmp_path / "usage.json", enforce=False)
    with worker._runtime(settings, audit):
        from rome.config import merge_with_default_config
        from rome.llm_handler import LLMHandler
        merged = merge_with_default_config(worker.build_config("Design a new game.", settings, tmp_path, "offline"))
        handler = SimpleNamespace(cost_limit=merged["LLMHandler"]["cost_limit"], accumulated_cost=1000.)
        # A disabled limit returns before token counting or cost estimation, even after a large spend.
        LLMHandler._check_and_log_cost(handler, [], 10000, worker.SOL)
    assert not audit.events and not audit.pending


@pytest.mark.parametrize('component', ['caesar_worker', 'caesar_metrics', 'caesar_budget'])
def test_identity_fingerprints_relocated_sibling_modules(tmp_path, monkeypatch, component):
    package = tmp_path / 'crest/providers'
    package.mkdir(parents=True)
    for name in ('caesar', 'caesar_worker', 'caesar_metrics', 'caesar_budget'):
        (package / f'{name}.py').write_text('version = 1\n')
    monkeypatch.setattr(caesar, '__file__', str(package / 'caesar.py'))
    settings = {'rome_path': str(tmp_path / 'rome')}
    before = caesar.identity_metadata(settings)
    assert caesar.identity_metadata(settings) == before
    (package / f'{component}.py').write_text('version = 2\n')
    assert caesar.identity_metadata(settings)['adapter_source_sha256'] != before['adapter_source_sha256']


@pytest.mark.parametrize('module', ['crest.caesar_worker', 'crest.providers.caesar_worker'])
def test_worker_identity_recognizes_legacy_and_relocated_commands(tmp_path, monkeypatch, module):
    import psutil
    result = str(tmp_path / 'caesar-result.json')
    command = ['python', '-m', module, '--result', result]
    process = SimpleNamespace(status=lambda: psutil.STATUS_RUNNING, cmdline=lambda: command)
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    assert caesar._worker_alive({'worker_pid': 43210, 'result_path': result})
    assert not caesar._worker_alive({'worker_pid': 43210, 'result_path': str(tmp_path / 'unrelated.json')})
    command[2] = 'unrelated.worker'
    assert not caesar._worker_alive({'worker_pid': 43210, 'result_path': result})


@ROME_WORKER
def test_runtime_default_rome_path_stays_sibling_of_checkout(monkeypatch):
    import builtins
    original_import, paths = builtins.__import__, []
    def intercept(name, *args, **kwargs):
        if name == 'openai':
            paths.append(Path(worker.sys.path[0]))
            raise ImportError('stop before importing the external runtime')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(worker.sys, 'path', worker.sys.path[:])
    monkeypatch.setattr(builtins, '__import__', intercept)
    with pytest.raises(ImportError, match='stop before importing'):
        with worker._runtime({}, None):
            pytest.fail('external runtime must not execute')
    assert paths == [Path(ROME)]



def _real_sdk_chat(audit, transport, asynchronous, **changes):
    """Exercise the installed SDK request boundary; only the HTTP transport is fake."""
    import httpx
    from openai import OpenAI, AsyncOpenAI
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    params = {"model": worker.SOL, "messages": [], "max_completion_tokens": 100, **changes}
    with audit.installed(SyncAPIClient, AsyncAPIClient):
        if asynchronous:
            async def call():
                async with AsyncOpenAI(api_key="offline-fixture", max_retries=0,
                        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                    return await client.chat.completions.create(**params)
            return asyncio.run(call())
        with OpenAI(api_key="offline-fixture", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            return client.chat.completions.create(**params)


def _sdk_chat_reply(*, usage=True, model=worker.SOL):
    import httpx
    data = {"id": "offline", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "answer"}}]}
    if usage:
        data["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    return httpx.Response(200, json=data)


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("extra_body", [
    {"max_completion_tokens": 1_000_000}, {"max_tokens": 1_000_000},
    {"model": "unpriced-helper"}, {"messages": [{"role": "user", "content": "x" * 10000}]},
], ids=["completion-limit", "legacy-limit", "model", "input"])
def test_hard_sdk_audit_rejects_late_json_overrides_before_dispatch(tmp_path, asynchronous, extra_body):
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        return _sdk_chat_reply()
    audit = worker.UsageAudit(.01, tmp_path / "usage.json")
    with pytest.raises(worker.BudgetExceeded):
        _real_sdk_chat(audit, transport, asynchronous, extra_body=extra_body)
    assert not sent and not audit.events and not audit.pending
    assert json.loads(audit.path.read_text())["in_flight"] == []


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("changes,output_rate", [
    ({"model": "unpriced-helper"}, None), ({"max_completion_tokens": None}, None),
    ({"max_completion_tokens": 0}, None), ({"max_completion_tokens": True}, None),
    ({}, -1.), ({}, float("nan")), ({}, True),
], ids=["unknown-price", "missing-limit", "zero-limit", "boolean-limit",
        "negative-price", "nan-price", "boolean-price"])
def test_hard_sdk_audit_rejects_unpriced_invalid_price_or_unbounded_dispatch(tmp_path, asynchronous, changes, output_rate):
    sent = []
    def transport(request):
        sent.append(1)
        return _sdk_chat_reply()
    prices = None if output_rate is None else {worker.SOL: {"input": 2., "output": output_rate}}
    audit = worker.UsageAudit(5, tmp_path / "usage.json", prices)
    with pytest.raises(worker.BudgetExceeded):
        _real_sdk_chat(audit, transport, asynchronous, **changes)
    assert not sent and not audit.pending and not audit.events


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("output_rate", [-1., float("nan"), True])
def test_soft_sdk_audit_refuses_invalid_prices_and_keeps_persisting(tmp_path, asynchronous, output_rate):
    # Regression: a soft cap reserved NaN, after which every usage.json write failed (allow_nan=False).
    sent = []
    def transport(request):
        sent.append(1)
        return _sdk_chat_reply(model=worker.LUNA)
    prices = {worker.SOL: {"input": 2., "output": output_rate}}
    audit = worker.UsageAudit(5, tmp_path / "usage.json", prices, enforce=False)
    with pytest.raises(worker.SDKRequestFailed, match=f"Invalid Caesar price for {worker.SOL}"):
        _real_sdk_chat(audit, transport, asynchronous)
    assert not sent and not audit.pending
    _real_sdk_chat(audit, transport, asynchronous, model=worker.LUNA)
    assert json.loads((tmp_path / "usage.json").read_text())["successful_calls"] == 1


def test_worker_records_an_invalid_price_failure(tmp_path, monkeypatch):
    class Agent(FakeAgent):
        def __init__(self, **kwargs): pass
        def explore(self): audits[0].before(_options())
        def shutdown(self): pass
    audits = []
    @contextmanager
    def runtime(settings, audit):
        audits.append(audit)
        yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    settings = {"budget_cap": "soft", "model_pricing": {worker.SOL: {"input": 2., "output": float("nan")}}}
    request = {"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "output"), "job_key": "abc"}
    assert worker.run_worker(request, tmp_path / "result.json") == 1
    record = json.loads((tmp_path / "result.json").read_text())
    assert record["status"] == "failed" and "Invalid Caesar price" in record["error"]
    assert record["usage"]["in_flight"] == [] and json.loads((tmp_path / "output" / "usage.json").read_text())["events"] == []


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("model,cost", [(worker.SOL, .0004), (worker.LUNA, .00002)])
def test_hard_sdk_audit_allows_empty_extra_body_and_keeps_exact_usage(tmp_path, asynchronous, model, cost):
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        assert audit.snapshot()["in_flight"][0]["reserved_usd"] > 0
        return _sdk_chat_reply(model=model)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    _real_sdk_chat(audit, transport, asynchronous, model=model, extra_body={})
    assert len(sent) == 1 and sent[0]["max_completion_tokens"] == 100
    assert audit.snapshot()["cost_usd"] == pytest.approx(cost)
    assert not audit.pending


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("changes", [
    {"extra_body": {"max_completion_tokens": 1_000_000}},
    {"model": "unpriced-helper"}, {"max_completion_tokens": None},
], ids=["late-override", "unknown-price", "missing-limit"])
def test_soft_sdk_audit_keeps_legacy_admission(tmp_path, asynchronous, changes):
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        return _sdk_chat_reply()
    audit = worker.UsageAudit(.00001, tmp_path / "usage.json", enforce=False)
    _real_sdk_chat(audit, transport, asynchronous, **changes)
    assert len(sent) == 1 and audit.snapshot()["successful_calls"] == 1
    if "extra_body" in changes:
        assert sent[0]["max_completion_tokens"] == 1_000_000
    if changes.get("model") == "unpriced-helper":
        assert audit.snapshot()["unknown_cost"] is True and audit.snapshot()["cost_usd"] is None


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("boundary", ["before-append", "after-pop"])
@pytest.mark.parametrize("status", [200, 500])
def test_sdk_settlement_signal_never_loses_paid_exposure(tmp_path, asynchronous, boundary, status):
    import httpx
    import signal
    audit = worker.UsageAudit(1, tmp_path / "usage.json", retry_attempts=1)
    _real_sdk_chat(audit, lambda request: _sdk_chat_reply(), asynchronous)
    prior = audit.snapshot()["known_cost_usd"]
    reserved = []
    def transport(request):
        reserved.append(audit.snapshot()["in_flight"][0]["reserved_usd"])
        return _sdk_chat_reply() if status == 200 else httpx.Response(500, json={"error": {"message": "offline failure"}})
    class InterruptedEvents(list):
        def append(self, event):
            if self is audit.events:  # Snapshot deepcopy must not trigger the settlement fault.
                signal.raise_signal(signal.SIGALRM)
            super().append(event)
    class InterruptedPending(dict):
        def pop(self, token, *args):
            value = super().pop(token, *args)
            signal.raise_signal(signal.SIGALRM)
            return value
    def stop(signum, frame):
        raise worker.WorkerDeadlineExceeded("offline settlement interruption")
    if boundary == "before-append":
        audit.events = InterruptedEvents(audit.events)
    else:
        audit.pending = InterruptedPending(audit.pending)
    previous = signal.signal(signal.SIGALRM, stop)
    try:
        with pytest.raises(worker.WorkerDeadlineExceeded):
            _real_sdk_chat(audit, transport, asynchronous)
    finally:
        signal.signal(signal.SIGALRM, previous)
    assert len(reserved) == 1
    audit.persist()  # A later failure snapshot must not overwrite away the paid exposure.
    saved = json.loads(audit.path.read_text())
    unresolved = saved["in_flight"] + [event for event in saved["events"] if event.get("unknown_cost")]
    exposure = saved["known_cost_usd"] + sum(event["reserved_usd"] for event in unresolved)
    assert exposure >= prior + (.0004 if status == 200 else reserved[0])
    assert len(saved["events"]) + len(saved["in_flight"]) >= 2
    if status == 500 or saved["in_flight"]:
        assert saved["unknown_cost"] is True and saved["cost_usd"] is None


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_hard_sdk_audit_retains_unpriced_accepted_response_reservation(tmp_path, asynchronous):
    audit = worker.UsageAudit(.002, tmp_path / "usage.json")
    sent = []
    def transport(request):
        sent.append(1)
        return _sdk_chat_reply(usage=False)
    _real_sdk_chat(audit, transport, asynchronous)
    saved = audit.snapshot()
    assert saved["events"][0]["unknown_cost"] is True
    assert worker._committed_spend(audit) == saved["events"][0]["reserved_usd"]
    with pytest.raises(worker.BudgetExceeded):
        _real_sdk_chat(audit, transport, asynchronous)
    assert len(sent) == 1


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("model,cost", [("text-embedding-3-small", .000001),
    ("text-embedding-3-large", .0000065), ("text-embedding-ada-002", .000005)])
def test_hard_sdk_audit_preserves_supported_embedding_requests(tmp_path, asynchronous, model, cost):
    import httpx
    from openai import OpenAI, AsyncOpenAI
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    audit = worker.UsageAudit(1, tmp_path / "usage.json")
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        assert audit.snapshot()["in_flight"][0]["reserved_usd"] > 0
        return httpx.Response(200, json={"object": "list", "model": model,
            "data": [{"object": "embedding", "index": 0, "embedding": [.1, .2]}],
            "usage": {"prompt_tokens": 50, "total_tokens": 50}})
    with audit.installed(SyncAPIClient, AsyncAPIClient):
        if asynchronous:
            async def call():
                async with AsyncOpenAI(api_key="offline-fixture", max_retries=0,
                        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                    await client.embeddings.create(model=model, input=["source"], encoding_format="float")
            asyncio.run(call())
        else:
            with OpenAI(api_key="offline-fixture", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
                client.embeddings.create(model=model, input=["source"], encoding_format="float")
    assert len(sent) == 1 and sent[0]["model"] == model
    assert audit.snapshot()["cost_usd"] == pytest.approx(cost)
    assert audit.snapshot()["successful_calls"] == 1 and not audit.pending



def test_quick_exploration_runs_past_old_time_limits_until_the_budget_reserve(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    accepted = threading.Barrier(2)
    calls, ingested = [], []
    class Agent:
        _crest_worker_started = 0
        current_iteration = 0
        visited_urls = {}
        shutdown_called = False
        def __init__(self):
            self.kb_manager = SimpleNamespace(add_texts=lambda values: ingested.extend(values))
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def _quick_perceive_and_think(self, url, iteration):
            calls.append(url)
            accepted.wait(timeout=5)
            clock.now = 7000  # Far past any per-phase time share; only the budget may stop pages.
            return {'url': url, 'insights': 'Collected', 'iteration': iteration}
        def explore(self):
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(lambda i: self._quick_perceive_and_think(str(i), i), range(4)))
            values = [value for value in values if value]
            self.visited_urls = {value['url']: 1 for value in values}
            self.current_iteration = max(value['iteration'] for value in values)
            self.kb_manager.add_texts(values)
            return self.synthesizer.synthesize_artifact()
    agent = Agent()
    artifact, stop = worker._quick_explore_with_synthesis_reserve(agent, {}, audit)
    assert artifact['artifact'] == 'Complete draft'
    assert len(calls) == len(ingested) == 4 and stop is None
    assert audit.exploration_limit is None


def test_ordinary_exploration_stops_only_on_the_budget_reserve(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    audit.events.append({'status': 'completed', 'cost_usd': 2.5, 'model': 'gpt-6-luna'})  # Reserve is $3 of $5.
    calls = []
    class Agent:
        _crest_worker_started = 0
        current_iteration = 0
        def __init__(self):
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def perceive(self):
            calls.append(self.current_iteration)
            clock.advance(9000)  # Hours pass; time alone never ends exploration.
        def explore(self):
            for iteration in range(1, 251):
                self.current_iteration = iteration
                self.perceive()
    agent = Agent()
    artifact, stop = worker._explore_with_synthesis_reserve(agent, {}, audit)
    assert calls == []  # Stopped before the first page: $2.50 committed exceeds the $2 exploration limit.
    assert stop['reason'] == 'budget_reserve' and 'time_limited' not in stop
    assert stop['iterations_completed'] == 0
    assert artifact['artifact'] == 'Complete draft'


def test_synthesis_allowance_is_money_only(tmp_path, monkeypatch):
    clock = Clock(7100)  # Would have been past every old time allowance.
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    calls = []
    class Synthesizer:
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        _current_draft = 1
        def _generate_qa_pairs(self):
            calls.append('genuine query')
            clock.advance(5000)
            return [('Question', 'Answer', [])]
    agent = SimpleNamespace(synthesizer=Synthesizer())
    with worker.adaptive_synthesis_budget(agent, {'budget_usd': 5}, audit) as records:
        assert agent.synthesizer._generate_qa_pairs() == [('Question', 'Answer', [])]
        assert audit.request_limit is None  # Restored after the draft's allowance.
    assert calls == ['genuine query']
    row = records['drafts'][0]
    assert row['completed_qa_rounds'] == 1 and row['budget_limited'] is False and row['qa_allowance_usd'] > 0
    assert 'time_policy' not in records and 'time_limited' not in row


@pytest.mark.parametrize("settings,expected", [({}, 21600), ({"timeout_seconds": 37}, 37)])
def test_worker_arms_one_monotonic_overall_deadline_with_generous_default_or_override(tmp_path, monkeypatch, settings, expected):
    clock = Clock(100)
    monkeypatch.setattr(worker, 'time', clock)
    seen = {'deadlines': []}
    @contextmanager
    def deadline(seconds):
        seen['deadlines'].append(seconds)
        yield
    class Agent:
        shutdown_called = False
        def __init__(self, **kwargs): clock.advance(3000)
        def perceive(self): clock.advance(4000)  # Exploration outlives the old 37.5% time share.
        def explore(self):
            self.current_iteration = 1
            self.perceive()
            return self.synthesizer.synthesize_artifact()
        @property
        def synthesizer(self):
            def synthesize():
                seen['start'] = self._crest_worker_started
                return {'artifact': 'A complete final answer', 'num_drafts': 3,
                        'metadata': {'synthesis_queries': 1}}
            return SimpleNamespace(synthesize_artifact=synthesize)
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, '_runtime', runtime)
    monkeypatch.setattr(worker, '_deadline', deadline)
    path = tmp_path / 'result.json'
    assert worker.run_worker({'prompt': 'Q', 'settings': settings, 'output_dir': str(tmp_path / 'output'),
                              'job_key': 'a' * 64}, path) == 0
    assert seen['start'] == 100
    assert seen['deadlines'] == [expected]  # The whole timeout, armed once before the agent starts.
    result = json.loads(path.read_text())['result']
    assert 'exploration_budget_stop' not in result['raw']


@pytest.mark.parametrize("effort,expected_hold,expected_allowance", [
    (None, 2.1, .3), ("xhigh", 2.4, .2), ("medium", 2.1, .3), ("high", 2.1, .3)])
def test_xhigh_synthesis_hold_is_unclamped_and_legacy_hold_stays_clamped(
        tmp_path, monkeypatch, effort, expected_hold, expected_allowance):
    audit = worker.UsageAudit(4, tmp_path / "usage.json")
    audit.events.append({"status": "completed", "model": worker.SOL, "cost_usd": 1.})
    settings = {} if effort is None else {"synthesis_reasoning_effort": effort}
    supplied = dict(settings)
    held = []
    def write_hold(effective, remaining, merge):
        held.append((dict(effective), remaining, merge))
        return 2.4
    monkeypatch.setattr(worker, "write_hold", write_hold)
    class Synthesizer:
        synthesis_drafts, synthesis_iterations, synthesis_merge_artifacts = 3, 20, True
        def _generate_qa_pairs(self):
            assert audit.request_limit == pytest.approx(1 + expected_allowance)
            return [("Q", "A", [])]
    synth = Synthesizer()
    original = synth._generate_qa_pairs
    with worker.adaptive_synthesis_budget(SimpleNamespace(synthesizer=synth), settings, audit) as report:
        assert synth._generate_qa_pairs() == [("Q", "A", [])]
    row = report["drafts"][0]
    assert row["remaining_write_allowance_usd"] == pytest.approx(expected_hold)
    assert row["qa_allowance_usd"] == pytest.approx(expected_allowance)
    assert held[0][0]["synthesis_reasoning_effort"] == (effort or "high")
    assert held[0][0]["max_completion_tokens"] == 32768
    assert held[0][1:] == (3, True)
    assert settings == supplied
    assert audit.request_limit is None and audit.request_limited is False
    assert synth._generate_qa_pairs == original


@pytest.mark.parametrize("hold", [2., 2.5])
def test_xhigh_synthesis_skips_qa_when_only_write_headroom_remains(tmp_path, monkeypatch, hold):
    audit = worker.UsageAudit(4, tmp_path / "usage.json")
    audit.events.append({"status": "completed", "model": worker.SOL, "cost_usd": 2.})
    monkeypatch.setattr(worker, "write_hold", lambda *args: hold)
    class Synthesizer:
        synthesis_drafts, synthesis_iterations, synthesis_merge_artifacts = 3, 20, True
        def _generate_qa_pairs(self): pytest.fail("Q&A must not run without funds outside the write hold")
    synth = Synthesizer()
    with worker.adaptive_synthesis_budget(SimpleNamespace(synthesizer=synth), {"synthesis_reasoning_effort": "xhigh"}, audit) as report:
        assert synth._generate_qa_pairs() == []
    row = report["drafts"][0]
    assert row["qa_allowance_usd"] == 0 and row["remaining_write_allowance_usd"] == hold
    assert row["completed_qa_rounds"] == 0 and row["budget_limited"] is True
    assert audit.request_limit is None and audit.request_limited is False
    # A retained heuristic hold is not permission to send an unaffordable actual write.
    with pytest.raises(worker.BudgetExceeded):
        _real_sdk_chat(audit, lambda request: pytest.fail("Unaffordable write dispatched"),
                       False, max_completion_tokens=1_000_000)


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("prior", ["none", "known", "pending", "unknown-completed"])
def test_qa_projected_reservation_must_fit_allowance_before_sdk_dispatch(tmp_path, asynchronous, prior):
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    limit = .001
    if prior == "known":
        audit.events.append({"status": "completed", "model": worker.SOL, "cost_usd": .0004})
        limit = .0015
    elif prior == "pending":
        audit.before(SimpleNamespace(json_data={"model": worker.SOL, "messages": [], "max_completion_tokens": 100}))
        limit = .002
    elif prior == "unknown-completed":
        _real_sdk_chat(audit, lambda request: _sdk_chat_reply(usage=False), asynchronous)
        limit = .002
    initial = audit.snapshot()
    audit.request_limit = limit
    sent = []
    def transport(request):
        sent.append(1)
        return _sdk_chat_reply()
    with pytest.raises(worker.BudgetExceeded):
        _real_sdk_chat(audit, transport, asynchronous)
    assert not sent and audit.request_limited is True
    assert audit.snapshot() == initial


@pytest.mark.parametrize("enforce,limit", [(True, .002), (False, .0001)])
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_qa_admission_allows_fitting_reservation_and_explicit_soft_mode(tmp_path, asynchronous, enforce, limit):
    audit = worker.UsageAudit(5, tmp_path / "usage.json", enforce=enforce)
    audit.request_limit = limit
    sent = []
    def transport(request):
        sent.append(1)
        return _sdk_chat_reply()
    _real_sdk_chat(audit, transport, asynchronous)
    assert len(sent) == 1 and not audit.request_limited
    assert audit.snapshot()["cost_usd"] == pytest.approx(.0004)


def test_worker_implicit_high_uses_non_xhigh_hold_from_budget_helper(tmp_path):
    audit = worker.UsageAudit(4, tmp_path / "usage.json")
    audit.events.append({"status": "completed", "model": worker.SOL, "cost_usd": 1.4})
    class Synthesizer:
        synthesis_drafts, synthesis_iterations, synthesis_merge_artifacts = 3, 20, True
        def _generate_qa_pairs(self): return [("Q", "A", [])]
    synth = Synthesizer()
    with worker.adaptive_synthesis_budget(SimpleNamespace(synthesizer=synth), {}, audit) as report:
        synth._generate_qa_pairs()
    # High uses the existing non-xhigh write/refinement allowance, not the xhigh policy.
    row = report["drafts"][0]
    assert row["remaining_write_allowance_usd"] == pytest.approx(.74268)
    assert row["qa_allowance_usd"] == pytest.approx((2.6 - .74268) / 3)
