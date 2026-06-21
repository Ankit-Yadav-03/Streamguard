# stream_guard/providers/ollama_provider.py

import aiohttp
import asyncio
import json


class OllamaProducer:
    """
    ClientProducer for Ollama streaming API.

    Guarantees:
    - Emits raw tokens via out()
    - Never emits EOS
    - Stops promptly on cancel_event
    """

    def __init__(
        self,
        *,
        model: str,
        prompt: str,
        base_url: str = "http://localhost:11434",
    ):
        self._model = model
        self._prompt = prompt
        self._base_url = base_url.rstrip("/")

    async def run(self, *, out, cancel_event: asyncio.Event) -> None:
        url = f"{self._base_url}/api/generate"

        payload = {
            "model": self._model,
            "prompt": self._prompt,
            "stream": True,
        }

        timeout = aiohttp.ClientTimeout(total=None)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()

                async for line in resp.content:
                    if cancel_event.is_set():
                        return

                    try:
                        data = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue

                    # Ollama emits incremental tokens here
                    token = data.get("response")
                    if token:
                        await out(token)

                    # Ollama signals done → just return
                    if data.get("done"):
                        return


# Example usage
async def main():
    producer = OllamaProducer(model="llama3", prompt="test")
    cancel_event = asyncio.Event()

    async def out(token):
        print(f"Received token: {token}")

    try:
        await producer.run(out=out, cancel_event=cancel_event)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())