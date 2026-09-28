"""Server-side Pollinations image generation helpers."""

from urllib.parse import quote
from io import BytesIO

import httpx

from app.core.config import settings


async def generate_assignment_image(prompt: str) -> tuple[bytes, str]:
    """Generate one image, keeping the Pollinations API key off the browser."""
    if not settings.pollinations_api_key:
        raise RuntimeError("Image generation is not configured. Add POLLINATIONS_API_KEY to the backend environment.")

    clean_prompt = " ".join((prompt or "").split())
    if not clean_prompt or len(clean_prompt) > 800:
        raise ValueError("Enter an image prompt between 1 and 800 characters.")

    base_url = settings.pollinations_base_url.rstrip("/")
    url = f"{base_url}/image/{quote(clean_prompt, safe='')}"
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            params={"model": settings.pollinations_image_model, "width": 768, "height": 768, "nologo": "true"},
            headers={"Authorization": f"Bearer {settings.pollinations_api_key}"},
        )
        if response.status_code in (401, 402):
            raise RuntimeError("Pollinations rejected the key or its available usage credits. Check the provider account.")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise RuntimeError("Pollinations returned a non-image response.")
        if len(response.content) > 8 * 1024 * 1024:
            raise RuntimeError("The generated image exceeded the 8 MB processing limit.")
        try:
            from PIL import Image
            with Image.open(BytesIO(response.content)) as image:
                image.thumbnail((768, 768))
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="JPEG", quality=82, optimize=True)
                return output.getvalue(), "image/jpeg"
        except Exception as exc:
            raise RuntimeError("The generated image could not be converted for report storage.") from exc
