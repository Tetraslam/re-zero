"""Anthropic client factory for server-side (non-Modal) usage."""

import os


def get_anthropic_client():
    """Return an Anthropic or AnthropicBedrock client based on USE_BEDROCK env."""
    if os.environ.get("USE_BEDROCK") == "true":
        from anthropic import AnthropicBedrock

        return AnthropicBedrock(
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        )
    from anthropic import Anthropic

    return Anthropic()


def get_model_id(model_name: str) -> str:
    """Map model names to Bedrock model IDs when using Bedrock."""
    if os.environ.get("USE_BEDROCK") != "true":
        return model_name
    mapping = {
        "claude-haiku-4-5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        "claude-sonnet-4-5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
    }
    return mapping.get(model_name, model_name)
