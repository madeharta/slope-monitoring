from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from services.rinex_service.cache import RINEXCache
from services.rinex_service.public_provider import (
    DEFAULT_PUBLIC_NAV_SOURCES,
    PublicNavigationSource,
    PublicRINEXDownloadError,
    PublicRINEXNavigationProvider,
)
from services.rinex_service.resolver import (
    RINEXNavigationResolver,
    RINEXResolutionError,
    ResolvedNavigation,
)


class RINEXAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NavigationAcquisitionResult:
    resolved: ResolvedNavigation
    cache_hit: bool
    provider: str | None


class RINEXNavigationAcquisition:
    def __init__(
        self,
        cache: RINEXCache,
        *,
        sources: tuple[PublicNavigationSource, ...] = DEFAULT_PUBLIC_NAV_SOURCES,
        provider_factory=None,
    ) -> None:
        self.cache = cache
        self.sources = sources
        self.resolver = RINEXNavigationResolver(cache)
        self._provider_factory = provider_factory or (
            lambda source: PublicRINEXNavigationProvider(cache, source)
        )

    def ensure(self, observed_at: datetime, *, station: str | None = None) -> NavigationAcquisitionResult:
        try:
            return NavigationAcquisitionResult(
                resolved=self.resolver.resolve(observed_at, station=station),
                cache_hit=True,
                provider=None,
            )
        except RINEXResolutionError:
            pass
        failures: list[str] = []
        for source in self.sources:
            try:
                self._provider_factory(source).fetch(observed_at)
                resolved = self.resolver.resolve(observed_at, station=station)
                return NavigationAcquisitionResult(
                    resolved=resolved,
                    cache_hit=False,
                    provider=source.name,
                )
            except (PublicRINEXDownloadError, RINEXResolutionError) as exc:
                failures.append(f"{source.name}: {exc}")
        detail = "; ".join(failures) if failures else "no public navigation providers configured"
        raise RINEXAcquisitionError(
            f"unable to acquire broadcast navigation for observation timestamp: {detail}"
        )
