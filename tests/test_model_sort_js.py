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


IMAGE_RULE_IDS = [
    "docker.io/ai/stable-diffusion:latest", "gpt-image-1", "gpt-image-1.5", "dall-e-3", "chatgpt-image-latest",
    "openai/gpt-5-image", "black-forest-labs/flux-dev", "flux.1-schnell", "sdxl-turbo", "hidream-i1",
    "qwen-image-edit", "z-image-turbo", "krea-2", "boogu-1",
    "huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M", "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S",
    "docker.io/ai/gemma3:latest", "gpt-4o", "gpt-5", "claude-sonnet-4", "qwen3-vl-30b-a3b-instruct",
    "speaches-ai/Kokoro-82M-v1.0-ONNX", "whisper-1", "tts-1", "text-embedding-3-small",
    "huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M", "sha256:5165bd2b9fec", "",
]


def test_image_model_rule_matches_the_servers_rule():
    """The picker lists a model under "Image generation" only if the server will
    answer it with an image, so the JS rule must agree with src/image_model_ids.py."""
    from src.image_model_ids import looks_like_image_generation_model

    values = _node_eval(
        """
        import { isImageModelId } from './static/js/modelSort.js';
        const ids = %s;
        console.log(JSON.stringify(ids.filter(isImageModelId)));
        """ % json.dumps(IMAGE_RULE_IDS)
    )

    assert values == [i for i in IMAGE_RULE_IDS if looks_like_image_generation_model(i)]
    assert "docker.io/ai/stable-diffusion:latest" in values
    assert "huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M" not in values
