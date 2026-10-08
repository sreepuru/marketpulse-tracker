from agents.ollama_client import OllamaClient, OllamaConfig


def test_default_models():
    config = OllamaConfig()

    assert config.gemma_model == "gemma3:4b"
    assert config.verifier_model == "qwen3:8b"
    assert config.embedding_model == "nomic-embed-text:latest"

def test_verifier_model_defaults_to_qwen3():
    config = OllamaConfig()

    assert config.verifier_model == "qwen3:8b"

def test_generate_json_sends_think_false(monkeypatch):
    client = OllamaClient()

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["path"] = path
        captured["payload"] = payload
        captured["timeout"] = timeout

        return {
            "response": '{"decision":"MATCH","security_id":2079}'
        }

    monkeypatch.setattr(client, "_post", fake_post)

    result = client.generate_json(
        model="qwen3:8b",
        system="test system",
        prompt="test prompt",
        think=False,
    )

    assert result["decision"] == "MATCH"
    assert result["security_id"] == 2079

    assert captured["path"] == "/api/generate"
    assert captured["payload"]["model"] == "qwen3:8b"
    assert captured["payload"]["think"] is False
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["options"]["temperature"] == 0