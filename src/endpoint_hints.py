"""Plain-language messages for model servers that do not answer.

"Cannot reach http://127.0.0.1:11434" says nothing about what should be listening there or what to
do. For the usual local ports, name the server and how to start it.
"""

from urllib.parse import urlsplit

# port -> (what normally listens there, how to start it)
_LOCAL_SERVERS = {
    11434: ("Ollama", "Start Ollama (or the Docker container that serves it)"),
    12434: ("Docker Model Runner", "Start Docker Desktop"),
    1234: ("LM Studio", "Start LM Studio's local server"),
    8000: ("a vLLM or Speaches server", "Start that server"),
    8080: ("a llama.cpp server", "Start that server"),
}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def unreachable_message(host_url: str) -> str:
    """``host_url`` is scheme://host:port, as ``llm_core._host_key`` returns it."""
    try:
        parts = urlsplit(host_url)
        port, host = parts.port, (parts.hostname or "")
    except ValueError:
        return f"Cannot reach {host_url}"
    if host not in _LOCAL_HOSTS:
        return f"Cannot reach {host_url}. Check that the server is running and the address is right."
    name, how = _LOCAL_SERVERS.get(port, (None, "Start the server"))
    what = f"{name} is not running there" if name else "nothing is listening there"
    return f"Cannot reach {host_url}: {what}. {how}, or pick another model."
