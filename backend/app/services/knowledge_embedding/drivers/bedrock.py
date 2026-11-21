"""AWS Bedrock embedding driver (Titan / Cohere).

Uses the standard AWS credential chain (env / instance role). Per-provider
credential wiring through the control plane is a later slice; this driver works
with an ambient AWS identity and region. Any missing dependency, credential, or
API failure raises loudly instead of degrading to hash vectors.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ...error_facts import error_type
from .base import FAMILY_BEDROCK, BaseEmbeddingDriver, EmbeddingConfigurationError


class BedrockEmbeddingDriver(BaseEmbeddingDriver):
    provider_id = FAMILY_BEDROCK

    def __init__(
        self,
        *,
        model: str,
        version: str,
        region: str | None = None,
        client_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.version = version
        self._region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        self._client = self._build_client(dict(client_kwargs or {}))

    def _build_client(self, client_kwargs: dict[str, Any]) -> Any:
        try:
            import boto3
        except Exception as exc:  # pragma: no cover - boto3 is a base dependency
            raise EmbeddingConfigurationError("Bedrock embeddings require boto3.") from exc
        if self._region and "region_name" not in client_kwargs:
            client_kwargs["region_name"] = self._region
        try:
            return boto3.client("bedrock-runtime", **client_kwargs)
        except Exception as exc:
            raise EmbeddingConfigurationError(
                f"Could not create the Bedrock client (error_type={error_type(exc)})."
            ) from exc

    def _invoke_titan(self, text: str) -> list[float]:
        response = self._client.invoke_model(modelId=self.model, body=json.dumps({"inputText": text}))
        payload = json.loads(response["body"].read())
        return [float(value) for value in payload["embedding"]]

    def _invoke_cohere(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps(
            {"texts": list(texts), "input_type": "search_document", "embedding_types": ["float"]}
        )
        response = self._client.invoke_model(modelId=self.model, body=body)
        payload = json.loads(response["body"].read())
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, dict):
            embeddings = embeddings.get("float")
        if not isinstance(embeddings, list):
            raise EmbeddingConfigurationError(f"Unexpected Cohere embedding response for '{self.model}'.")
        return [[float(value) for value in row] for row in embeddings]

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        try:
            if "cohere" in self.model.lower():
                return self._invoke_cohere(texts)
            return [self._invoke_titan(text) for text in texts]
        except EmbeddingConfigurationError:
            raise
        except Exception as exc:
            raise EmbeddingConfigurationError(
                f"Bedrock embedding call failed for model '{self.model}' (error_type={error_type(exc)})."
            ) from exc
