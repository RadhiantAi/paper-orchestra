"""Provider-neutral requests. SDKs and credentials are loaded only when used."""

import base64
import mimetypes
import os
import re
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from utils.response_parsing import parse_json_results

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class ModelConfigurationError(ValueError):
    pass


class ModelResponseError(RuntimeError):
    pass


def resolve_model(model_name=None):
    model_name = model_name or os.getenv("PAPER_WRITER_MODEL", "")
    if not model_name:
        raise ModelConfigurationError(
            "Set PAPER_WRITER_MODEL or --writer_model_name to provider:model."
        )
    if ":" in model_name:
        provider, model = model_name.split(":", 1)
    elif model_name.startswith("gemini-"):
        provider, model = "gemini", model_name
    elif model_name.startswith("claude-"):
        provider, model = "anthropic", model_name
    elif model_name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")):
        provider, model = "openai", model_name
    else:
        raise ModelConfigurationError(
            "Use an explicit provider:model name for this model."
        )
    if (
        provider not in {"openai", "gemini", "anthropic", "compatible"}
        or not model.strip()
    ):
        raise ModelConfigurationError(
            "Provider must be openai, gemini, anthropic or compatible, followed by a model ID."
        )
    return provider, model


def model_file_label(model_name=None):
    """Stable model identifier that is safe in Windows and POSIX filenames."""
    provider, model = resolve_model(model_name)
    identifier = f"{provider}:{model}"
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", identifier)[:100].rstrip(". ")
    digest = hashlib.sha256(identifier.encode()).hexdigest()[:8]
    return f"{label}_{digest}"


def validate_model_configuration(model_name):
    """Check configuration without creating clients or making requests."""
    provider, _ = resolve_model(model_name)
    if (
        provider == "gemini"
        and os.getenv("VERTEX_AI_PROJECT")
        and os.getenv("VERTEX_AI_LOCATION")
    ):
        return
    required = {
        "openai": ("OPENAI_API_KEY",),
        "gemini": ("GEMINI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "compatible": ("LLM_BASE_URL",),
    }[provider]
    for name in required:
        if not os.getenv(name):
            raise ModelConfigurationError(
                f"Set {name} for the selected {provider} provider."
            )
    if provider == "compatible":
        from urllib.parse import urlparse

        url = urlparse(os.environ["LLM_BASE_URL"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ModelConfigurationError(
                "LLM_BASE_URL must be an HTTP(S) URL without embedded credentials."
            )
        if url.scheme == "http" and url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ModelConfigurationError("Use HTTPS for a remote compatible endpoint.")


def _client(provider):
    timeout = float(os.getenv("PAPER_API_TIMEOUT", "300"))
    if provider in {"openai", "compatible"}:
        from openai import OpenAI

        if provider == "compatible":
            return OpenAI(
                api_key=os.getenv("LLM_API_KEY") or "local-no-key",
                base_url=os.environ["LLM_BASE_URL"],
                timeout=timeout,
                max_retries=2,
            )
        return OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url="https://api.openai.com/v1",
            timeout=timeout,
            max_retries=2,
        )
    if provider == "anthropic":
        from anthropic import Anthropic

        return Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url="https://api.anthropic.com",
            timeout=timeout,
            max_retries=2,
        )
    from google import genai
    from google.genai import types

    options = {"http_options": types.HttpOptions(timeout=int(timeout * 1000))}
    if os.getenv("VERTEX_AI_PROJECT") and os.getenv("VERTEX_AI_LOCATION"):
        return genai.Client(
            vertexai=True,
            project=os.environ["VERTEX_AI_PROJECT"],
            location=os.environ["VERTEX_AI_LOCATION"],
            **options,
        )
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"], **options)


def _parts(contents):
    """Normalise text and binary images. Expand PDFs for every provider alike."""
    result = []
    for item in contents:
        if isinstance(item, str):
            result.append({"text": item})
        elif item.get("mime_type") == "application/pdf":
            import pymupdf

            with pymupdf.open(stream=item["data"], filetype="pdf") as document:
                result.append({"text": "\n".join(page.get_text() for page in document)})
                for page in document:
                    result.append(
                        {
                            "data": page.get_pixmap(dpi=100).tobytes("png"),
                            "mime_type": "image/png",
                        }
                    )
        elif "text" in item or item.get("mime_type", "").startswith("image/"):
            result.append(item)
        else:
            raise ValueError("Unsupported content type; provide text, images or PDF.")
    return result


def _request(provider, model, parts, system, temperature, max_tokens):
    client = _client(provider)
    try:
        return _request_with_client(
            client, provider, model, parts, system, temperature, max_tokens
        )
    finally:
        client.close()


def _request_with_client(
    client, provider, model, parts, system, temperature, max_tokens
):
    if provider in {"openai", "compatible"}:
        content = []
        for part in parts:
            if "text" in part:
                content.append({"type": "text", "text": part["text"]})
            else:
                data = base64.b64encode(part["data"]).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{part['mime_type']};base64,{data}"},
                    }
                )
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content})
        options = {
            "max_completion_tokens"
            if provider == "openai"
            else "max_tokens": max_tokens
        }
        if provider == "compatible" and temperature is not None:
            options["temperature"] = temperature
        response = client.chat.completions.create(
            model=model, messages=messages, **options
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise ModelResponseError(
                "Model response was truncated, refused or requested an unsupported tool."
            )
        return choice.message.content
    if provider == "anthropic":
        content = []
        for part in parts:
            if "text" in part:
                content.append({"type": "text", "text": part["text"]})
            else:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part["mime_type"],
                            "data": base64.b64encode(part["data"]).decode("ascii"),
                        },
                    }
                )
        options = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
        if system:
            options["system"] = system
        with client.messages.stream(**options) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "end_turn":
            raise ModelResponseError(
                "Model response was incomplete or requested an unsupported tool."
            )
        return "\n".join(
            block.text for block in response.content if block.type == "text"
        )
    from google.genai import types

    content = [
        types.Part.from_text(text=p["text"])
        if "text" in p
        else types.Part.from_bytes(data=p["data"], mime_type=p["mime_type"])
        for p in parts
    ]
    options = {"max_output_tokens": max_tokens}
    if system:
        options["system_instruction"] = system
    if temperature is not None:
        options["temperature"] = temperature
    response = client.models.generate_content(
        model=model, contents=content, config=types.GenerateContentConfig(**options)
    )
    if (
        not response.candidates
        or str(response.candidates[0].finish_reason).split(".")[-1] != "STOP"
    ):
        raise ModelResponseError("Model response was incomplete or blocked.")
    return response.text


def call_llm_with_contents(
    contents,
    model_name=None,
    generation_configs=None,
    check_parsed_response_not_none=True,
    return_json=True,
    result_parsing_func=None,
):
    provider, model = resolve_model(model_name)
    validate_model_configuration(model_name)
    config = dict(generation_configs or {})
    system = config.pop("system_instruction", None)
    temperature = config.pop("temperature", None)
    max_tokens = int(
        config.pop("max_output_tokens", os.getenv("PAPER_MAX_OUTPUT_TOKENS", "16384"))
    )
    if config:
        raise ModelConfigurationError(
            "Unsupported generation option; use provider-neutral settings."
        )
    if max_tokens <= 0:
        raise ModelConfigurationError("PAPER_MAX_OUTPUT_TOKENS must be positive.")
    parts = _parts(contents)
    try:
        raw = _request(provider, model, parts, system, temperature, max_tokens)
    except ModelResponseError:
        raise
    except Exception:
        raise ModelResponseError(
            f"{provider} request failed. Check model access, credentials and API limits."
        ) from None
    if not isinstance(raw, str) or not raw.strip():
        raise ModelResponseError("Model returned no text.")
    parser = result_parsing_func or (parse_json_results if return_json else lambda x: x)
    try:
        parsed = parser(raw)
    except Exception:
        raise ModelResponseError("Model response could not be parsed.") from None
    if check_parsed_response_not_none and parsed is None:
        raise ModelResponseError(
            "Model response did not contain the required structured output."
        )
    return {"raw_response": raw, "parsed_response": parsed}


def get_llm_parser(model_name=None, return_json=True):
    return parse_json_results if return_json else lambda x: x


def call_llm_with_text_prompt(prompt, model_name=None, **kwargs):
    return call_llm_with_contents([prompt], model_name, **kwargs)


def call_llm_with_images(prompt, images, model_name=None, **kwargs):
    parts = [prompt]
    for image in images:
        parts.append(
            {
                "data": Path(image).read_bytes(),
                "mime_type": mimetypes.guess_type(str(image))[0] or "image/png",
            }
        )
    return call_llm_with_contents(parts, model_name, **kwargs)


def call_llm_with_pdf(
    pdf_path,
    prompt,
    model_name=None,
    system_instruction=None,
    temperature=0.7,
    **kwargs,
):
    return call_llm_with_contents(
        [{"data": Path(pdf_path).read_bytes(), "mime_type": "application/pdf"}, prompt],
        model_name,
        generation_configs={
            "system_instruction": system_instruction,
            "temperature": temperature,
        },
        **kwargs,
    )
