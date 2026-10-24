"""Execute the actual Pages generator/verifier against a poisoned scratch build."""
import ast
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import ROOT, git

CANARY = 'QA_PRIVATE_FEED_CANARY_do_not_publish'


def pages_python_blocks():
    workflow = (ROOT / '.github/workflows/pages-demo.yml').read_text()
    return [textwrap.dedent(block) for block in re.findall(r"python - <<'PY'\n(.*?)\n\s+PY(?:\n|$)", workflow, re.S)]


def test_pages_workflow_uploads_only_demo_build():
    workflow = (ROOT / '.github/workflows/pages-demo.yml').read_text()
    assert 'path: web/dist' in workflow
    assert 'npm run build --prefix web' in workflow
    blocks = pages_python_blocks()
    assert len(blocks) >= 2
    assert 'demo=True' in blocks[0] and 'read_demo()' in blocks[0]
    assert '!= "demo"' in blocks[0] and '== "demo"' in blocks[-1]
    assert workflow.index('Verify artifact is demo-only') < workflow.index('uses: actions/upload-pages-artifact')
    # Inspect executable YAML lines, not comments describing what is prohibited.
    commands = '\n'.join(line for line in workflow.splitlines() if not line.lstrip().startswith('#'))
    assert not re.search(r'(?:python\s+-m\s+(?:tools\.publish_observability|ingest\.live)|--source\s+t3\b|curl\s|wget\s)', commands)


def test_pages_actual_build_excludes_poisoned_private_fixtures_and_feeds(tmp_path, monkeypatch):
    # Reuse already installed locked dependencies; never download packages in a QA test.
    common = Path(git('rev-parse', '--git-common-dir')).resolve().parent
    candidates = [ROOT / 'web/node_modules', common / 'web/node_modules']
    deps = next((p for p in candidates if (p / '.bin/vite').exists()), None)
    if deps is None or shutil.which('npm') is None:
        pytest.skip('Offline frontend dependencies unavailable; install locked dependencies to run artifact proof')
    scratch = tmp_path / 'public build'
    scratch.mkdir()
    for name in ('web', 'shared', 'fixtures', 'schema'):
        shutil.copytree(ROOT / name, scratch / name,
                        ignore=shutil.ignore_patterns('node_modules', 'dist', '.git'))
    (scratch / 'web/node_modules').symlink_to(deps.resolve(), target_is_directory=True)
    for path in (scratch / 'fixtures/observability').glob('live-*.json'):
        doc = json.loads(path.read_text())
        doc['notes'].append(CANARY)
        path.write_text(json.dumps(doc))
    for name in ('activity.json', 'latest.json', 'summary.md'):
        (scratch / name).write_text(CANARY)
    result = subprocess.run(['npm', 'run', 'build', '--prefix', 'web', '--', '--base', '/agent-mindmap/'],
                            cwd=scratch, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    monkeypatch.chdir(scratch)
    for block in pages_python_blocks():
        exec(compile(block, 'pages-demo.yml', 'exec'), {'__name__': '__qa_pages__'})
    dist = scratch / 'web/dist'
    for artifact in dist.rglob('*'):
        if artifact.is_file():
            assert CANARY.encode() not in artifact.read_bytes(), artifact.relative_to(dist)
    activity = json.loads((dist / 'activity.json').read_text())
    assert activity['meta']['t3']['mode'] == 'demo'
    assert all(n['session']['source'] == 'pages-demo' for n in activity['nodes'])
    if (dist / 'observability.json').exists():
        assert json.loads((dist / 'observability.json').read_text())['mode'] == 'demo'


SDK_ROOTS = {'openai', 'anthropic', 'litellm', 'cohere', 'mistralai', 'groq', 'google.generativeai',
             'google.genai', 'google_genai', 'langchain_openai', 'langchain_anthropic'}
ENDPOINTS = re.compile(r'(?:/chat/completions|/v1/completions|/v1/messages|/v1/responses|:generateContent|:streamGenerateContent)', re.I)
CALL_SUFFIXES = ('chat.completions.create', 'completions.create', 'responses.create', 'messages.create',
                 'generate_content', 'generateContent', 'streamGenerateContent')


def forbidden_model_calls(source):
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(name == sdk or name.startswith(sdk + '.') for name in names for sdk in SDK_ROOTS):
                violations.append(node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and ENDPOINTS.search(node.value):
            violations.append(node.lineno)
        if isinstance(node, ast.Call):
            dotted = ast.unparse(node.func)
            if dotted.endswith(CALL_SUFFIXES):
                violations.append(node.lineno)
            if dotted in {'__import__', 'importlib.import_module'} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and arg.value in SDK_ROOTS:
                    violations.append(node.lineno)
    return violations


def test_tools_and_ingest_have_zero_model_calls():
    violations = []
    paths = [*ROOT.joinpath('tools').rglob('*.py'), *ROOT.joinpath('ingest').rglob('*.py')]
    assert paths
    for path in paths:
        for line in forbidden_model_calls(path.read_text()):
            violations.append(f'{path.relative_to(ROOT)}:{line}')
    assert not violations, violations


@pytest.mark.parametrize('code', [
    'import openai as innocent', 'from anthropic import Anthropic',
    'importlib.import_module("openai")', 'client.chat.completions.create(model="fake")',
    'post("https://api.example.invalid/v1/messages")',
])
def test_zero_model_guard_detects_synthetic_regressions(code):
    assert forbidden_model_calls(code)
