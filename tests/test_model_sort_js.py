import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node_eval(source: str):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_model_sort_helpers_ignore_non_arrays():
    values = _node_eval(
        """
        import { sortModelIds, sortModelObjects } from './static/js/modelSort.js';
        console.log(JSON.stringify({
          idsObject: sortModelIds({bad: true}),
          idsString: sortModelIds('llama'),
          objectsNull: sortModelObjects(null),
          objectsObject: sortModelObjects({bad: true})
        }));
        """
    )

    assert values == {
        "idsObject": [],
        "idsString": [],
        "objectsNull": [],
        "objectsObject": [],
    }


def test_model_sort_helpers_keep_valid_arrays():
    values = _node_eval(
        """
        import { sortModelIds, sortModelObjects } from './static/js/modelSort.js';
        console.log(JSON.stringify({
          ids: sortModelIds(['zeta/10', 'alpha/2', 'alpha/11']),
          objects: sortModelObjects([{id: 'zeta/10'}, {id: 'alpha/2'}]).map(m => m.id)
        }));
        """
    )

    assert values == {
        "ids": ["alpha/2", "zeta/10", "alpha/11"],
        "objects": ["alpha/2", "zeta/10"],
    }


def test_non_chat_model_ids_are_recognised_by_their_last_path_segment():
    values = _node_eval(
        """
        import { isNonChatModelId } from './static/js/modelSort.js';
        const ids = [
          'speaches-ai/Kokoro-82M-v1.0-ONNX', 'Systran/faster-whisper-small', 'whisper-1',
          'docker.io/ai/stable-diffusion:latest', 'huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M',
          'text-embedding-3-small', 'tts-1', 'gpt-image-1', 'flux.1-dev',
          'huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M', 'docker.io/ai/gemma3:latest',
          'gpt-4o', 'claude-sonnet-4', 'qwen2.5-coder-1.5b-instruct', 'sha256:5165bd2b9fec', '', null,
        ];
        console.log(JSON.stringify(ids.filter(isNonChatModelId)));
        """
    )

    assert values == [
        "speaches-ai/Kokoro-82M-v1.0-ONNX", "Systran/faster-whisper-small", "whisper-1",
        "docker.io/ai/stable-diffusion:latest",
        "huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M",
        "text-embedding-3-small", "tts-1", "gpt-image-1", "flux.1-dev",
    ]
