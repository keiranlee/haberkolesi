import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from domain import Category
from gemini_service import EditorialBatchResult, ScoreResult


@pytest.mark.asyncio
async def test_openai_structured_contract_and_result():
    from openai_service import OpenAITransport
    def respond(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["reasoning"] == {"effort": "none"}
        assert payload["store"] is False
        schema = payload["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["$defs"]["CandidateScore"]["additionalProperties"] is False
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"evaluations": []}'}]}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = OpenAITransport("test-key", client=client)
        result = await service.generate_json(model="gpt-5.4-mini", prompt="News", response_schema=EditorialBatchResult)
        assert result == {"evaluations": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"status": "incomplete", "output": []},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not JSON"}]}]},
])
async def test_bad_openai_response_is_not_accepted(body):
    from openai_service import OpenAITransport
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        with pytest.raises(ValueError, match="OpenAI"):
            await OpenAITransport("key", client=client).generate_json(model="gpt-5.4-mini", prompt="News", response_schema=ScoreResult)


def test_image_is_text_free_contextual_png_and_reused(tmp_path):
    from openai_service import OpenAIImageService
    buffer = BytesIO()
    Image.new("RGB", (1536, 1024), "blue").save(buffer, format="PNG")
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/v1/images/generations"
        assert payload["n"] == 1
        assert payload["quality"] == "low"
        assert "NO TEXT" in payload["prompt"]
        assert "Yeni çip" in payload["prompt"]
        assert "Enerji tüketimi azaldı" in payload["prompt"]
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = OpenAIImageService("key", tmp_path, client=client)
        path = service.generate_card(42, "Yeni çip", Category.TEKNOLOJI, "Source", key_fact="Enerji tüketimi azaldı")
        assert path.exists()
        with Image.open(path) as img:
            assert img.format == "PNG"
            assert img.size == (1536, 1024)
        assert service.generate_card(42, "Yeni başlık", Category.TEKNOLOJI, "Source") == path
        assert len(requests) == 1


def test_image_failure_does_not_replace_existing_gemini_card(tmp_path):
    from openai_service import OpenAIImageService
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (1200, 675)).save(images / "42.png")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"b64_json": "invalid"}]}))) as client:
        with pytest.raises(ValueError):
            OpenAIImageService("key", tmp_path, client=client).generate_card(42, "Chip", Category.AI, "Source")
    assert (images / "42.png").exists()
    assert not (images / "42-openai.png").exists()


@pytest.mark.asyncio
async def test_upstream_errors_preserve_status_without_exposing_response_body():
    from openai_service import OpenAITransport, OpenAIRequestError
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, json={"error": {"message": "secret-token"}}))) as client:
        with pytest.raises(OpenAIRequestError) as error:
            await OpenAITransport("secret-token", client=client).generate_json(model="gpt-5.4-mini", prompt="News", response_schema=ScoreResult)
        assert error.value.status_code == 429
        assert "secret-token" not in str(error.value)
