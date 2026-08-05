from __future__ import annotations

import hashlib
import html
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote

import httpx


CROSSREF_WORKS_URL = "https://api.crossref.org/works"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_USER_AGENT = "Nexus-AI-PC/0.1 (local research literature client)"
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0, read=15.0, write=10.0, pool=5.0)

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


class ResearchUpstreamError(RuntimeError):
    def __init__(self, provider: str, detail: str, *, status_code: int = 502) -> None:
        super().__init__(detail)
        self.provider = provider
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ResearchPaper:
    canonical_key: str
    doi: str | None
    title: str
    abstract: str | None
    authors: tuple[str, ...]
    publication_year: int | None
    publication_date: str | None
    venue: str | None
    paper_type: str | None
    citation_count: int | None
    url: str | None
    providers: tuple[str, ...]
    source_ids: dict[str, str]

    def as_record(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "doi": self.doi,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "publication_year": self.publication_year,
            "publication_date": self.publication_date,
            "venue": self.venue,
            "paper_type": self.paper_type,
            "citation_count": self.citation_count,
            "url": self.url,
            "providers": list(self.providers),
            "source_ids": dict(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    provider: str
    external_id: str
    doi: str | None
    title: str
    abstract: str | None
    authors: tuple[str, ...]
    publication_year: int | None
    publication_date: str | None
    venue: str | None
    paper_type: str | None
    citation_count: int | None
    url: str | None


class LiteratureClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent must not be blank")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 10) -> list[ResearchPaper]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be blank")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        candidates = [
            *self._search_crossref(query, limit),
            *self._search_openalex(query, limit),
        ]
        return _merge_candidates(candidates)

    def _search_crossref(self, query: str, limit: int) -> list[_Candidate]:
        params: dict[str, str | int] = {"query.bibliographic": query, "rows": limit}
        contact = os.getenv("AI_PC_RESEARCH_CONTACT", "").strip()
        if "@" in contact:
            params["mailto"] = contact
        payload = self._request_json("Crossref", CROSSREF_WORKS_URL, params)
        message = payload.get("message")
        items = message.get("items") if isinstance(message, Mapping) else None
        if not isinstance(items, list):
            raise ResearchUpstreamError("Crossref", "Crossref returned an unexpected response.")
        return [candidate for item in items if (candidate := _crossref_candidate(item)) is not None]

    def _search_openalex(self, query: str, limit: int) -> list[_Candidate]:
        openalex_query = _WHITESPACE.sub(" ", re.sub(r"[*?]+", " ", query)).strip()
        payload = self._request_json(
            "OpenAlex",
            OPENALEX_WORKS_URL,
            {"search": openalex_query, "per-page": limit},
        )
        items = payload.get("results")
        if not isinstance(items, list):
            raise ResearchUpstreamError("OpenAlex", "OpenAlex returned an unexpected response.")
        return [candidate for item in items if (candidate := _openalex_candidate(item)) is not None]

    def _request_json(
        self,
        provider: str,
        url: str,
        params: Mapping[str, str | int],
    ) -> dict[str, Any]:
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ResearchUpstreamError(
                provider,
                f"{provider} timed out. Try the search again later.",
                status_code=504,
            ) from error
        except httpx.RequestError as error:
            raise ResearchUpstreamError(
                provider,
                f"{provider} is currently unavailable. Check the network and try again.",
            ) from error

        if response.status_code >= 400:
            raise ResearchUpstreamError(
                provider,
                f"{provider} returned HTTP {response.status_code}. Try the search again later.",
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise ResearchUpstreamError(provider, f"{provider} returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise ResearchUpstreamError(provider, f"{provider} returned an unexpected response.")
        return payload


def normalize_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    doi = unquote(value).strip()
    doi = _DOI_PREFIX.sub("", doi).strip().lower()
    if not _DOI_PATTERN.fullmatch(doi):
        return None
    return doi


def _crossref_candidate(item: object) -> _Candidate | None:
    if not isinstance(item, Mapping):
        return None
    title = _first_text(item.get("title"))
    if not title:
        return None
    doi = normalize_doi(item.get("DOI"))
    external_id = _text(item.get("DOI")) or _text(item.get("URL")) or title
    publication_date = _crossref_date(item)
    publication_year = _integer(item.get("published"), minimum=1000, maximum=9999)
    if publication_year is None and publication_date:
        publication_year = int(publication_date[:4])
    authors: list[str] = []
    raw_authors = item.get("author")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            if not isinstance(author, Mapping):
                continue
            literal = _text(author.get("name"))
            name = literal or " ".join(
                part for part in (_text(author.get("given")), _text(author.get("family"))) if part
            )
            if name:
                authors.append(name)
    return _Candidate(
        provider="crossref",
        external_id=external_id,
        doi=doi,
        title=title,
        abstract=_clean_abstract(item.get("abstract")),
        authors=tuple(dict.fromkeys(authors)),
        publication_year=publication_year,
        publication_date=publication_date,
        venue=_first_text(item.get("container-title")),
        paper_type=_text(item.get("type")),
        citation_count=_integer(item.get("is-referenced-by-count"), minimum=0),
        url=_text(item.get("URL")) or (f"https://doi.org/{doi}" if doi else None),
    )


def _openalex_candidate(item: object) -> _Candidate | None:
    if not isinstance(item, Mapping):
        return None
    title = _text(item.get("display_name")) or _text(item.get("title"))
    if not title:
        return None
    doi = normalize_doi(item.get("doi"))
    external_id = _text(item.get("id")) or _text(item.get("doi")) or title
    authors: list[str] = []
    raw_authors = item.get("authorships")
    if isinstance(raw_authors, list):
        for authorship in raw_authors:
            if not isinstance(authorship, Mapping):
                continue
            author = authorship.get("author")
            if isinstance(author, Mapping):
                name = _text(author.get("display_name"))
                if name:
                    authors.append(name)
    primary_location = item.get("primary_location")
    source: object = None
    landing_page_url: object = None
    if isinstance(primary_location, Mapping):
        source = primary_location.get("source")
        landing_page_url = primary_location.get("landing_page_url")
    venue = _text(source.get("display_name")) if isinstance(source, Mapping) else None
    publication_date = _valid_iso_date(item.get("publication_date"))
    publication_year = _integer(item.get("publication_year"), minimum=1000, maximum=9999)
    if publication_year is None and publication_date:
        publication_year = int(publication_date[:4])
    return _Candidate(
        provider="openalex",
        external_id=external_id,
        doi=doi,
        title=title,
        abstract=_openalex_abstract(item.get("abstract_inverted_index")),
        authors=tuple(dict.fromkeys(authors)),
        publication_year=publication_year,
        publication_date=publication_date,
        venue=venue,
        paper_type=_text(item.get("type")),
        citation_count=_integer(item.get("cited_by_count"), minimum=0),
        url=_text(landing_page_url) or (f"https://doi.org/{doi}" if doi else external_id),
    )


def _merge_candidates(candidates: Iterable[_Candidate]) -> list[ResearchPaper]:
    merged: dict[str, ResearchPaper] = {}
    for candidate in candidates:
        canonical_key = _canonical_key(candidate)
        paper = ResearchPaper(
            canonical_key=canonical_key,
            doi=candidate.doi,
            title=candidate.title,
            abstract=candidate.abstract,
            authors=candidate.authors,
            publication_year=candidate.publication_year,
            publication_date=candidate.publication_date,
            venue=candidate.venue,
            paper_type=candidate.paper_type,
            citation_count=candidate.citation_count,
            url=candidate.url,
            providers=(candidate.provider,),
            source_ids={candidate.provider: candidate.external_id},
        )
        existing = merged.get(canonical_key)
        merged[canonical_key] = _merge_papers(existing, paper) if existing else paper
    return list(merged.values())


def _merge_papers(left: ResearchPaper, right: ResearchPaper) -> ResearchPaper:
    authors = tuple(dict.fromkeys((*left.authors, *right.authors)))
    providers = tuple(dict.fromkeys((*left.providers, *right.providers)))
    source_ids = {**left.source_ids, **right.source_ids}
    abstract = max((value for value in (left.abstract, right.abstract) if value), key=len, default=None)
    citations = [value for value in (left.citation_count, right.citation_count) if value is not None]
    return ResearchPaper(
        canonical_key=left.canonical_key,
        doi=left.doi or right.doi,
        title=max((left.title, right.title), key=len),
        abstract=abstract,
        authors=authors,
        publication_year=left.publication_year or right.publication_year,
        publication_date=left.publication_date or right.publication_date,
        venue=left.venue or right.venue,
        paper_type=left.paper_type or right.paper_type,
        citation_count=max(citations) if citations else None,
        url=left.url or right.url,
        providers=providers,
        source_ids=source_ids,
    )


def _canonical_key(candidate: _Candidate) -> str:
    if candidate.doi:
        return f"doi:{candidate.doi}"
    identity = "|".join(
        (
            candidate.provider,
            candidate.external_id.casefold(),
            _WHITESPACE.sub(" ", candidate.title).casefold(),
            str(candidate.publication_year or ""),
        )
    )
    return f"record:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _crossref_date(item: Mapping[str, object]) -> str | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = item.get(key)
        if not isinstance(value, Mapping):
            continue
        date_parts = value.get("date-parts")
        if not isinstance(date_parts, Sequence) or isinstance(date_parts, (str, bytes)) or not date_parts:
            continue
        parts = date_parts[0]
        if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
            continue
        numbers = [_integer(part, minimum=1) for part in parts[:3]]
        if not numbers or numbers[0] is None:
            continue
        year = numbers[0]
        month = numbers[1] if len(numbers) > 1 and numbers[1] is not None else 1
        day = numbers[2] if len(numbers) > 2 and numbers[2] is not None else 1
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def _openalex_abstract(value: object) -> str | None:
    if not isinstance(value, Mapping) or not value:
        return None
    positioned: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            parsed = _integer(position, minimum=0, maximum=100_000)
            if parsed is not None:
                positioned.append((parsed, token))
    if not positioned:
        return None
    positioned.sort(key=lambda item: item[0])
    return " ".join(token for _, token in positioned)


def _clean_abstract(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    cleaned = _WHITESPACE.sub(" ", _HTML_TAG.sub(" ", html.unescape(text))).strip()
    return cleaned or None


def _valid_iso_date(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _first_text(value: object) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    return next((_text(item) for item in value if _text(item)), None)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _WHITESPACE.sub(" ", value).strip()
    return normalized or None


def _integer(value: object, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Mapping):
        value = value.get("year")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed
