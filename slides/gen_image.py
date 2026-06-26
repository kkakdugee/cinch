"""Generate a slide image via an Azure OpenAI image deployment (e.g. gpt-image-2).

Usage:
  AZURE_OAI_TOKEN=<bearer> python gen_image.py <prompt_file> <out_png> [size] [quality]

Auth: pass an AAD bearer token (scope https://cognitiveservices.azure.com) in
AZURE_OAI_TOKEN, or an API key in AZURE_OAI_KEY.
"""
import base64
import json
import os
import sys
import urllib.request
import urllib.error

ENDPOINT = os.environ.get(
    "AZURE_OAI_ENDPOINT",
    "https://yanha-moorqdvl-westus3.cognitiveservices.azure.com",
).rstrip("/")
DEPLOYMENT = os.environ.get("AZURE_OAI_DEPLOYMENT", "gpt-image-2")
API_VERSIONS = [
    os.environ.get("AZURE_OAI_API_VERSION", "2025-04-01-preview"),
    "2024-02-01",
    "2025-01-01-preview",
]


def main():
    prompt_file = sys.argv[1]
    out_png = sys.argv[2]
    size = sys.argv[3] if len(sys.argv) > 3 else "1536x1024"
    quality = sys.argv[4] if len(sys.argv) > 4 else "high"

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    token = os.environ.get("AZURE_OAI_TOKEN")
    key = os.environ.get("AZURE_OAI_KEY")
    if not token and not key:
        print("ERROR: set AZURE_OAI_TOKEN or AZURE_OAI_KEY", file=sys.stderr)
        sys.exit(2)

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["api-key"] = key

    body = {"prompt": prompt, "n": 1, "size": size, "quality": quality}

    last_err = None
    for ver in API_VERSIONS:
        url = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/images/generations?api-version={ver}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            item = payload["data"][0]
            if item.get("b64_json"):
                img = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                with urllib.request.urlopen(item["url"], timeout=120) as r2:
                    img = r2.read()
            else:
                print("ERROR: no image in response:", json.dumps(payload)[:500])
                sys.exit(3)
            with open(out_png, "wb") as f:
                f.write(img)
            print(f"OK  api-version={ver}  bytes={len(img)}  -> {out_png}")
            if payload["data"][0].get("revised_prompt"):
                print("revised_prompt:", payload["data"][0]["revised_prompt"][:300])
            return
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            last_err = f"HTTP {e.code} (api-version={ver}): {detail[:600]}"
            # Only worth retrying other api-versions on 400/404.
            if e.code not in (400, 404):
                break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            break

    print("FAILED:", last_err, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
