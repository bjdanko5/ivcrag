from typing import List, Optional, Dict, Union, Any

from pydantic import BaseModel


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


class _ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

    @property
    def text(self) -> str:
        """Возвращает текстовое содержимое независимо от формата."""
        if isinstance(self.content, str):
            return self.content
        parts = []
        for item in self.content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)


class _ChatCompletionRequest(BaseModel):
    model: str = "rag"
    messages: List[_ChatMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False


__all__ = [
    "EmbedRequest",
    "EmbedResponse",
    "_ChatMessage",
    "_ChatCompletionRequest",
]
