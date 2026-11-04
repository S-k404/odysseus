"""src/endpoint_hints.py: say what should be listening on a dead local port and what to do."""

import pytest

from src.endpoint_hints import unreachable_message


@pytest.mark.parametrize("url, server, how", [
    ("http://127.0.0.1:11434", "Ollama", "Start Ollama"),
    ("http://localhost:12434", "Docker Model Runner", "Start Docker Desktop"),
    ("http://127.0.0.1:1234", "LM Studio", "Start LM Studio"),
])
def test_a_known_local_port_names_the_server_and_how_to_start_it(url, server, how):
    message = unreachable_message(url)
    assert message.startswith(f"Cannot reach {url}:")
    assert f"{server} is not running there" in message and how in message
    assert message.endswith("or pick another model.")


def test_an_unknown_local_port_says_nothing_is_listening():
    assert unreachable_message("http://127.0.0.1:9999") == (
        "Cannot reach http://127.0.0.1:9999: nothing is listening there. Start the server, or pick another model.")


def test_a_remote_host_is_not_told_to_start_anything_locally():
    message = unreachable_message("https://api.example.com")
    assert message.startswith("Cannot reach https://api.example.com.") and "Start" not in message


def test_a_malformed_address_is_passed_through():
    assert unreachable_message("http://127.0.0.1:notaport") == "Cannot reach http://127.0.0.1:notaport"
