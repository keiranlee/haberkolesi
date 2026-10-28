"""Persisted provider selection; each job holds one immutable service bundle."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderBundle:
    name: str
    text: Any
    images: Any


class AiProviders:
    def __init__(self, repository, *, gemini: Optional[ProviderBundle] = None, openai: Optional[ProviderBundle] = None):
        self.repository = repository
        self.providers = {"gemini": gemini, "openai": openai}

    def _resolve(self, name: str) -> ProviderBundle:
        if name not in self.providers:
            raise ValueError("Geçersiz AI sağlayıcısı")
        bundle = self.providers[name]
        if bundle is None:
            label, variable = ("OpenAI", "OPENAI_API_KEY") if name == "openai" else ("Gemini", "GEMINI_API_KEY")
            raise ValueError(f"{label} için {variable} ekleyip uygulamayı yeniden başlatın.")
        return bundle

    async def select(self, name: str) -> None:
        self._resolve(name)
        await self.repository.set_ai_provider(name)

    async def snapshot(self) -> ProviderBundle:
        return self._resolve(await self.repository.get_ai_provider())

    async def snapshot_for_job(self, job_id: int) -> ProviderBundle:
        selected = await self.repository.get_ai_provider()
        pinned = await self.repository.bind_job_provider(job_id, selected)
        return self._resolve(pinned)

    async def status(self):
        name = await self.repository.get_ai_provider()
        bundle = self.providers.get(name)
        gate = getattr(bundle.text, "gate", None) if bundle else None
        return {
            "selected": name,
            "label": "OpenAI (ChatGPT)" if name == "openai" else "Gemini",
            "openai_available": self.providers["openai"] is not None,
            "gemini_available": self.providers["gemini"] is not None,
            "rate_status": gate.status() if gate is not None else None,
        }
