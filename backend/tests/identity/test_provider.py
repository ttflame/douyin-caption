import httpx
import pytest

from app.modules.identity.provider import OpenAICompatibleConnectionTester


@pytest.mark.parametrize("html", [True, False])
async def test_connection_distinguishes_website_from_model_endpoint(monkeypatch, html):
    def respond(request):
        assert request.url.path == "/models"
        if html:
            return httpx.Response(
                200, text="<html>Website</html>", headers={"content-type": "text/html"}
            )
        return httpx.Response(200, json={"data": [{"id": "custom-model"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    result = await OpenAICompatibleConnectionTester().test(
        "test-key",
        "https://provider.example",
        "custom-model",
    )
    assert result.success is not html
    assert result.code == ("provider_invalid_endpoint" if html else "ok")
