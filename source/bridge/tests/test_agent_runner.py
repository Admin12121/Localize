import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from task_store import TaskStore
from agent_runner import AgentRunner, AgentRunnerError, OpenAIResponsesProvider


WS = {'workspace_id': 'selected-project', 'root': '/project', 'revision': 'abc123'}
CONFIG = {'enabled': True, 'model': 'explicit-model', 'api_key_env': 'BRIDGE_TEST_KEY',
          'max_steps': 3, 'max_seconds': 5, 'max_tokens': 4096,
          'tools': [{'type': 'function', 'name': 'write_file', 'description': 'Write file',
                     'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]}


def wait(runner, task_id):
    deadline = time.monotonic() + 3
    while runner.status(task_id)['running'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert not runner.status(task_id)['running']
    return runner.store.read(task_id)


def make(tmp_path, provider, execute=None, verify=None):
    store = TaskStore(tmp_path)
    task = store.create('Make proof', ['proof exists'], WS)
    runner = AgentRunner(store, execute or (lambda *a, **kw: {'success': True}),
                         verify or (lambda *a, **kw: {'verified': False, 'evidence': []}), provider=provider)
    return runner, task['task_id']


def test_configuration_and_import_never_call_provider(tmp_path, monkeypatch):
    calls = []
    runner, task = make(tmp_path, lambda **kw: calls.append(kw))
    runner.configure(CONFIG)
    assert calls == []
    with pytest.raises(AgentRunnerError, match='key'):
        runner.start(task, WS)
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    with pytest.raises(AgentRunnerError, match='workspace'):
        runner.start(task, {**WS, 'revision': 'changed'})
    assert calls == []
    runner.close()
    runner.store.close()


def test_model_final_text_cannot_complete_without_verifier_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    runner, task = make(tmp_path, lambda **kw: {'text': 'All done!', 'calls': [], 'usage': {'input_tokens': 10, 'output_tokens': 4}})
    runner.configure(CONFIG)
    runner.start(task, WS)
    assert wait(runner, task)['status'] == 'partial'
    runner.close()
    runner.store.close()


def test_real_executor_result_and_verifier_artifact_complete_task(tmp_path, monkeypatch):
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    artifact = tmp_path / 'proof.txt'
    steps = iter([{'calls': [{'name': 'write_file', 'arguments': {}}]}, {'text': 'Done', 'calls': []}])
    def execute(name, arguments, **context):
        assert context['workspace'] == WS
        artifact.write_text('actual artifact')
        return {'success': True, 'artifact': str(artifact)}
    def verify(task, **context):
        return {'verified': artifact.read_text() == 'actual artifact',
                'evidence': [{'path': str(artifact), 'sha256': __import__('hashlib').sha256(artifact.read_bytes()).hexdigest()}]}
    runner, task = make(tmp_path, lambda **kw: {**next(steps), 'usage': {'input_tokens': 20, 'output_tokens': 10}}, execute, verify)
    runner.configure(CONFIG)
    runner.start(task, WS)
    saved = wait(runner, task)
    assert saved['status'] == 'completed'
    assert saved['evidence'][-1]['sha256']
    runner.close()
    runner.store.close()


def test_pending_approval_pauses_after_one_submission_and_is_not_replayed_on_resume(tmp_path, monkeypatch):
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    submissions = []
    requests = []
    def provider(**kw):
        requests.append(kw)
        return {'calls': [{'name': 'write_file', 'arguments': {}}], 'usage': {'input_tokens': 20, 'output_tokens': 10}}
    def execute(*args, **kw):
        submissions.append(args)
        return {'state': 'awaiting_approval', 'job_id': 'saved-command', 'approval_required': True}
    runner, task = make(tmp_path, provider, execute)
    runner.configure(CONFIG)
    runner.start(task, WS)
    saved = wait(runner, task)
    assert saved['status'] == 'awaiting_approval'
    assert len(submissions) == 1
    runner.start(task, WS)
    assert wait(runner, task)['status'] == 'blocked'
    assert len(submissions) == 1
    assert 'saved-command' in str(requests[-1]['task'])
    runner.close()
    runner.store.close()


def test_step_and_token_budgets_stop_before_more_side_effects(tmp_path, monkeypatch):
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    executed = []
    runner, task = make(tmp_path, lambda **kw: {'calls': [{'name': 'write_file', 'arguments': {}}],
                                             'usage': {'input_tokens': 4000, 'output_tokens': 1000}},
                        lambda *a, **kw: executed.append(a))
    runner.configure(CONFIG)
    runner.start(task, WS)
    assert wait(runner, task)['status'] == 'partial'
    assert executed == []
    runner.close()
    runner.store.close()


def test_cancel_during_provider_does_not_execute_returned_command(tmp_path, monkeypatch):
    monkeypatch.setenv('BRIDGE_TEST_KEY', 'fixture-not-secret')
    entered, release = threading.Event(), threading.Event()
    executed = []
    def provider(**kw):
        entered.set()
        release.wait(2)
        return {'calls': [{'name': 'write_file', 'arguments': {}}], 'usage': {'input_tokens': 10, 'output_tokens': 10}}
    runner, task = make(tmp_path, provider, lambda *a, **kw: executed.append(a))
    runner.configure(CONFIG)
    runner.start(task, WS)
    assert entered.wait(1)
    runner.cancel(task)
    release.set()
    assert wait(runner, task)['status'] == 'cancelled'
    assert executed == []
    runner.close()
    runner.store.close()


def test_openai_provider_uses_documented_responses_and_no_automatic_retry():
    class Responses:
        def count_tokens(self, **kw):
            return type('Count', (), {'input_tokens': 50})()
        def create(self, **kw):
            assert kw['model'] == CONFIG['model']
            assert kw['store'] is False
            assert kw['parallel_tool_calls'] is False
            return type('Response', (), {'output': [], 'output_text': 'done',
                                         'usage': type('Usage', (), {'input_tokens': 50, 'output_tokens': 10})()})()
    class Client:
        responses = Responses()
    provider = OpenAIResponsesProvider(client=Client())
    result = provider(task={'intent': 'test'}, history=[], config=CONFIG, remaining_tokens=1000, timeout_seconds=2)
    assert result['text'] == 'done'
    assert result['usage']['input_tokens'] == 50
