"""Offline Caesar protocol, isolation, and SDK accounting checks."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from crest.providers import caesar
from crest import caesar_worker as worker


class FakeAgent:
    def perceive(self): return "content", []


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
    assert first["ArtifactSynthesizer"]["synthesis_top_k"] == 15
    assert first["ArtifactSynthesizer"]["synthesis_generate_images"] == 0
    assert first["ArtifactSynthesizer"]["synthesis_merge_clarify"] is False
    assert first["BraveSearch"]["use_ddgs"] is True
    assert first["ChromaClientManager"]["enable_reranking"] is False
    assert first["LLMHandler"]["model"] == "gpt-6.1-sol"
    assert first["LLMHandler"]["cost_limit"] == 5
    assert first["LLMHandler"]["max_completion_tokens"] == 25000
    assert first["LLMHandler"]["timeout"] == 600
    assert first["CaesarAgent"]["exploration_llm_config"]["timeout"] == 600
    assert first["LLMHandler"]["max_input_tokens"] == 64000
    assert first["CaesarAgent"]["exploration_llm_config"]["max_completion_tokens"] == 2000
    assert first["CaesarAgent"]["exploration_llm_config"]["model"] == "gpt-6-luna"
    assert first["ChromaClientManager"]["model"] == "gpt-6-luna"
    assert second["CaesarAgent"]["exploration_llm_config"]["model"] == "custom-explore"
    assert second["ChromaClientManager"]["model"] == "custom-kb"
    assert first["ChromaClientManager"]["collection_name"] != second["ChromaClientManager"]["collection_name"]
    assert first["ChromaServerManager"]["persist_path"] != second["ChromaServerManager"]["persist_path"]
    assert first["AgentMemory"]["enabled"] is False


def test_extract_result_preserves_abstract_full_artifact_and_source_map():
    result = completed()["result"]
    assert "An abstract." in result["text"]
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


def test_identity_changes_when_rome_source_changes_without_reading_env(tmp_path):
    (tmp_path / "caesar").mkdir()
    source = tmp_path / "caesar" / "caesar_agent.py"
    source.write_text("version = 1\n")
    (tmp_path / ".env").write_text("never include credentials")
    old = caesar.identity_metadata({"rome_path": str(tmp_path)})
    source.write_text("version = 2\n")
    assert old != caesar.identity_metadata({"rome_path": str(tmp_path)})
    assert "credentials" not in json.dumps(old)


def test_completed_local_worker_is_replayed_without_subprocess(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(completed()))
    job = Job(tmp_path, {"result_path": str(path), "worker_pid": 123})
    async def no_launch(*args, **kwargs):
        pytest.fail("must replay persisted result")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_launch)
    assert asyncio.run(caesar.generate("Q", {}, job))["text"] == completed()["result"]["text"]


def test_launch_persists_pid_and_result_without_serializing_secrets(tmp_path, monkeypatch):
    job = Job(tmp_path)
    async def launch(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        assert job.state["submission_unknown"] is True
        request = json.loads(Path(args[args.index("--request") + 1]).read_text())
        assert "api_key" not in json.dumps(request)
        Path(args[args.index("--result") + 1]).write_text(json.dumps(completed()))
        class Child:
            pid = 876
            returncode = 0
            async def wait(self): return 0
        return Child()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(caesar.generate("Q", {"api_key": "do-not-write-this"}, job))
    assert result["text"]
    assert job.state["worker_pid"] == 876
    assert job.state["submission_unknown"] is False


def test_resumed_live_worker_is_waited_for_without_duplicate_launch(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    job = Job(tmp_path, {"result_path": str(path), "worker_pid": 876, "worker_started_at": time.time()})
    monkeypatch.setattr(caesar, "_worker_alive", lambda state: True)
    async def sleep(_): path.write_text(json.dumps(completed()))
    async def no_launch(*args, **kwargs): pytest.fail("duplicate worker")
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_launch)
    assert asyncio.run(caesar.generate("Q", {}, job))["text"]


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


def test_scoped_compatibility_registers_prices_reasoning_and_llama_models():
    class Handler:
        MODEL_PRICING = {"old": {"input": 1, "output": 2}}
        MODEL_CONTEXT_SIZE = {"old": 1}
        REASONING_MODELS = {"old"}
        _known_models_registered = True
    config = {"LLMHandler": {"max_completion_tokens": 10000}}
    llama = SimpleNamespace(O1_MODELS={}, CHAT_MODELS={}, ALL_AVAILABLE_MODELS={})
    llm = SimpleNamespace(register_model=lambda entries: None)
    with worker.compatibility(Handler, config, llm, llama, 2000):
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
    assert not llama.CHAT_MODELS
    assert config["LLMHandler"]["max_completion_tokens"] == 10000


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


def test_compatibility_registers_tokenizer_without_persisting_global_change():
    class Handler:
        MODEL_PRICING, MODEL_CONTEXT_SIZE, REASONING_MODELS = {}, {}, set()
        _known_models_registered = False
    llama = SimpleNamespace(O1_MODELS={}, CHAT_MODELS={}, ALL_AVAILABLE_MODELS={})
    registry = {}
    with worker.compatibility(Handler, {"LLMHandler": {"max_completion_tokens": 10000}}, SimpleNamespace(register_model=lambda _: None), llama, 2000, tokenizer_registry=registry):
        assert registry["gpt-6.1-sol"] == "o200k_base"
    assert registry == {}


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


def test_worker_has_own_timeout_when_parent_is_interrupted(tmp_path, monkeypatch):
    class Agent(FakeAgent):
        shutdown_called = False
        def __init__(self, **kwargs): pass
        def explore(self):
            time.sleep(.1)
            return artifact()
        def shutdown(self): self.shutdown_called = True
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    assert worker.run_worker({"prompt": "Q", "settings": {"timeout_seconds": .01}, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 1
    assert "Deadline" in json.loads(path.read_text())["error"]


def test_sdk_audit_rejects_truncated_chat_output_but_keeps_billed_usage(tmp_path):
    class SDK:
        def request(self, cast_to, options, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20), choices=[SimpleNamespace(finish_reason="length")])
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(ValueError, match="incomplete"):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
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
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
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


def test_real_rome_handler_and_llama_kb_offline_validation(tmp_path, monkeypatch):
    """Exercise installed LiteLLM validation and SDK payloads without network access."""
    import socket
    import httpx
    monkeypatch.setenv("OPENAI_API_KEY", "offline-regression-test")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    sent = []
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
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
            assert handler.chat_completion("Q", override_config={"model": "gpt-6-luna", "reasoning_effort": "low"}) == '{"artifact":"complete"}'
            llama = LlamaOpenAI(model="gpt-6-luna", api_key="offline-regression-test", max_tokens=2000, additional_kwargs={"reasoning_effort": "low"})
            assert llama.chat([ChatMessage(role="user", content="Q")]).message.content == '{"artifact":"complete"}'
    assert len(sent) == 3
    assert sent[0]["reasoning_effort"] == "medium"
    assert sent[1]["reasoning_effort"] == "low"
    assert sent[2]["reasoning_effort"] == "low"
    assert audit.snapshot()["successful_calls"] == 3


def test_fatal_deadline_passes_actual_rome_synthesis_catch_and_cleans_up(tmp_path, monkeypatch):
    audit = worker.UsageAudit(5, tmp_path / "setup-usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
        from caesar.artifact_synthesis import ArtifactSynthesizer
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


@pytest.mark.parametrize("usage", [{"prompt_tokens": 1000}, {"completion_tokens": 100}])
def test_missing_essential_chat_usage_keeps_cost_unknown(tmp_path, usage):
    class SDK:
        def request(self, *args, **kwargs): return SimpleNamespace(usage=usage)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
    assert audit.snapshot()["unknown_cost"] is True
    assert audit.snapshot()["cost_usd"] is None


@pytest.mark.parametrize("details,expected", [({"cache_write_tokens": 1000}, .0035), ({"cached_tokens": 1000}, .0011), ({"cached_tokens": 400, "cache_write_tokens": 200}, .00234)])
def test_sol_cache_write_and_read_tokens_are_part_of_total_input(tmp_path, details, expected):
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": details})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
    assert audit.snapshot()["cost_usd"] == pytest.approx(expected)


def test_sol_long_context_applies_rates_to_whole_request(tmp_path):
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 272001, "completion_tokens": 100})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
    assert audit.snapshot()["cost_usd"] == pytest.approx(1.089504)


def test_invalid_cache_token_partition_cannot_report_known_cost(tmp_path):
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 200}})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
    assert audit.snapshot()["cost_usd"] is None
    assert audit.snapshot()["unknown_cost"] is True


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
    settings = {"handler_budget_usd": 4., "synthesis_reserve_usd": reserve, "model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 1000000}}}
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


def test_sdk_retries_confirmed_rate_limit_once_without_double_billing(tmp_path, monkeypatch):
    import httpx
    from openai import OpenAI
    from openai._base_client import SyncAPIClient
    requests, waits = [], []
    def transport(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"message": "try later", "code": "rate_limit_exceeded", "type": "rate_limit_error"}})
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": "gpt-6.1-sol", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "answer"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    audit = worker.UsageAudit(.002, tmp_path / "usage.json")
    with audit.installed(SyncAPIClient), OpenAI(api_key="offline", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        assert client.chat.completions.create(model="gpt-6.1-sol", messages=[], max_completion_tokens=100).choices[0].message.content == "answer"
    usage = audit.snapshot()
    assert len(requests) == 2
    assert waits == [3]
    assert usage["rate_limit_events"] == 1
    assert usage["failed_calls"] == 1
    assert usage["successful_calls"] == 1
    assert usage["unknown_cost"] is False
    assert usage["cost_usd"] == pytest.approx(.0004)
    assert usage["events"][0]["reserved_usd"] == 0
    assert usage["events"][0]["cost_usd"] == 0


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
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100}))
    assert len(attempts) == expected_attempts
    assert audit.snapshot()["cost_usd"] == 0
    assert audit.snapshot()["unknown_cost"] is False


def test_async_sdk_rate_retry_keeps_exact_attempt_usage(tmp_path, monkeypatch):
    attempts, waits = [], []
    class Rejected(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"Retry-After": "2"})
    class Sync:
        def request(self, *args, **kwargs): pytest.fail("sync request")
    class Async:
        async def request(self, *args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1: raise Rejected()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    async def sleep(delay): waits.append(delay)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    audit = worker.UsageAudit(.002, tmp_path / "usage.json")
    with audit.installed(Sync, Async):
        asyncio.run(Async().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100})))
    assert len(attempts) == 2
    assert waits == [2]
    assert audit.snapshot()["rate_limit_events"] == 1
    assert audit.snapshot()["cost_usd"] == pytest.approx(.0004)


def test_unparseable_paid_response_retains_unknown_cost_reservation(tmp_path):
    attempts = []
    class BadResponse:
        def parse(self): raise ValueError("unparseable response")
    class SDK:
        def request(self, *args, **kwargs):
            attempts.append(1)
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20}) if len(attempts) == 1 else BadResponse()
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    options = SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100})
    with audit.installed(SDK):
        SDK().request(object, options)
        with pytest.raises(worker.SDKRequestFailed): SDK().request(object, options)
    assert audit.snapshot()["cost_usd"] is None
    assert audit.snapshot()["unknown_cost"] is True
    assert audit.snapshot()["in_flight"]


def test_bad_accepted_response_cannot_reenter_actual_rome_paid_retry_loop(tmp_path):
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
        from caesar.artifact_synthesis import ArtifactSynthesizer
    paid = []
    class BadResponse:
        def parse(self): raise ValueError("accepted response could not be decoded")
    class SDK:
        def request(self, *args, **kwargs):
            paid.append(1)
            if len(paid) == 1: return BadResponse()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20}, text='{"artifact":"complete"}')
    options = SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100})
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
        asyncio.run(Async().request(object, SimpleNamespace(json_data={"model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 100})))
    assert len(paid) == 1
    assert audit.snapshot()["cost_usd"] is None
    assert len(audit.snapshot()["in_flight"]) == 1


def test_chroma_start_uses_worker_interpreter_without_chroma_on_path(tmp_path, monkeypatch):
    """Exercise Rome's real startup lifecycle with a local fake Chroma CLI."""
    import atexit
    import socket
    import sys
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
        from rome.kb_server import ChromaServerManager
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
        "persist_path": str(tmp_path / "store"), "startup_timeout": 3, "shutdown_timeout": 1})
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
    assert audit.snapshot()["successful_calls"] == 0


def test_parallel_quick_exploration_reserves_synthesis_budget_and_ingests_completed_pages(tmp_path, monkeypatch):
    """Run Rome's quick loop, including its real executor and result ingestion."""
    import threading
    import networkx as nx
    audit = worker.UsageAudit(5, tmp_path / "setup-usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
        from caesar.caesar_agent import CaesarAgent
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
            self.logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None)
            self.checkpoint_manager = SimpleNamespace(save=lambda *args, **kwargs: None)
            self.kb_manager = SimpleNamespace(add_texts=self.ingest)
            self.synthesizer = SimpleNamespace(synthesize_artifact=self.synthesize)
        def perceive(self):
            return "seed", [(f"https://page.test/{i}", "page") for i in range(250)]
        def _quick_perceive_and_think(self, url, iteration):
            pay("page")
            return {"url": url, "insights": "insight", "iteration": iteration}
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
    settings = {"synthesis_reserve_usd": 3., "handler_budget_usd": 5., "model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 1000000}}}
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


def test_adaptive_qa_budget_finishes_three_drafts_and_merge(tmp_path, monkeypatch):
    setup_audit = worker.UsageAudit(5, tmp_path / "setup-usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, setup_audit):
        from caesar.artifact_synthesis import ArtifactSynthesizer
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
            pay("merge", 4)
            return artifact(metadata={"synthesis_queries": len(drafts[-1])})
        def synthesize_artifact(self):
            drafts = []
            for index in range(1, 4):
                self._current_draft = index
                pairs = self._generate_qa_pairs()
                assert pairs
                pay("draft", 4)
                drafts.append(pairs)
                if index < 3: pay("refine", 2)
            return self._merge_artifacts(drafts)
    class Agent(FakeAgent):
        starting_query = "question"
        def __init__(self, **kwargs):
            self.synthesizer = Synthesizer()
            self.synthesizer.agent = self
        def chat_completion(self, *args, **kwargs):
            pay("next_query", 2)
            return '{"query":"next question"}'
        def parse_json_response(self, value): return json.loads(value)
        def explore(self):
            pay("exploration", 20)
            return self.synthesizer.synthesize_artifact()
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "result.json"
    settings = {"model_pricing": {"gpt-6.1-sol": {"input": 0, "output": 50000}}}
    assert worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "output"), "job_key": "abc"}, path) == 0
    result = json.loads(path.read_text())["result"]
    assert calls.count("draft") == 3
    assert calls.count("merge") == 1
    assert result["cost_usd"] <= 5
    records = result["raw"]["synthesis_budget"]["drafts"]
    assert len(records) == 3
    assert all(1 <= row["completed_qa_rounds"] <= 15 for row in records)
    assert any(row["completed_qa_rounds"] < 15 for row in records)
    assert any(row["budget_limited"] for row in records)
    assert result["raw"]["synthesis_budget"]["merge_completed"] is True


@pytest.mark.parametrize("inputs,details,expected", [(1000, {"cache_write_tokens": 1000}, .000175), (272001, {}, .0544752)])
def test_latest_luna_usage_uses_verified_cache_and_long_context_prices(tmp_path, inputs, details, expected):
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": inputs, "completion_tokens": 100, "prompt_tokens_details": details})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK):
        SDK().request(object, SimpleNamespace(json_data={"model": "gpt-6-luna", "messages": [], "max_completion_tokens": 100}))
    assert audit.snapshot()["cost_usd"] == pytest.approx(expected)


def recovery_source(tmp_path):
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
    worker.atomic_json(source / "caesar-request.json", {"prompt": "Q", "worker_id": "original-worker", "job_key": "original-job", "settings": {"budget_usd": 5}})
    worker.atomic_json(source / "caesar-result.json", {"status": "failed", "error": "ambiguous timeout", "usage": {"known_cost_usd": .45898205, "unknown_cost": True, "budget_target_usd": 5,
        "events": [{"status": "failed", "unknown_cost": True, "reserved_usd": .2114525}], "in_flight": []}})
    return source


def test_explicit_recovery_copies_store_and_uses_rome_checkpoint_without_exploration(tmp_path, monkeypatch):
    audit = worker.UsageAudit(5, tmp_path / "setup-usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome")}, audit):
        from caesar.checkpoint import CheckpointManager
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
    request = {"prompt": "Q", "settings": {"recovery_from": str(source), "budget_usd": 4.3, "handler_budget_usd": 4.3}, "output_dir": str(path.parent / "output"), "job_key": "new-job"}
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


@pytest.mark.parametrize("timeout", [600, 37])
def test_runtime_timeout_reaches_sdk_even_when_library_supplies_shorter_value(tmp_path, timeout):
    import openai
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with worker._runtime({"rome_path": str(Path(__file__).resolve().parents[2] / "rome"), "call_timeout_seconds": timeout}, audit):
        with openai.OpenAI(api_key="offline", timeout=1) as client:
            assert client.timeout == timeout
            assert client.with_options(timeout=1).timeout == timeout
    assert audit.snapshot()["successful_calls"] == 0


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
