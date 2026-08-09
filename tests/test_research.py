from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.research import LiteratureClient, ResearchUpstreamError, normalize_doi


def _create_project(client: TestClient) -> int:
    response = client.post(
        "/api/research/projects",
        json={
            "name": "Evidence review",
            "question": "Does retrieval practice improve durable learning?",
            "research_type": "systematic review",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _crossref_payload() -> dict:
    return {
        "status": "ok",
        "message": {
            "items": [
                {
                    "DOI": "10.1000/SHARED",
                    "title": ["Retrieval practice and durable learning"],
                    "abstract": "<jats:p>Practice improves long-term retention.</jats:p>",
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "published-print": {"date-parts": [[2024, 2, 3]]},
                    "container-title": ["Learning Science"],
                    "type": "journal-article",
                    "is-referenced-by-count": 8,
                    "URL": "https://doi.org/10.1000/shared",
                },
                {
                    "title": ["A Crossref-only record"],
                    "author": [{"name": "Research Group"}],
                    "published-online": {"date-parts": [[2023]]},
                    "URL": "https://example.test/crossref-only",
                },
            ]
        },
    }


def _openalex_payload() -> dict:
    return {
        "meta": {"count": 2},
        "results": [
            {
                "id": "https://openalex.org/W100",
                "doi": "https://doi.org/10.1000/shared",
                "display_name": "Retrieval practice and durable learning: a controlled study",
                "abstract_inverted_index": {
                    "Long-term": [0],
                    "retention": [1],
                    "improved": [2],
                },
                "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                "publication_year": 2024,
                "publication_date": "2024-02-03",
                "primary_location": {
                    "landing_page_url": "https://example.test/shared",
                    "source": {"display_name": "Learning Science"},
                },
                "type": "article",
                "cited_by_count": 12,
            },
            {
                "id": "https://openalex.org/W200",
                "doi": "https://doi.org/10.2000/openalex-only",
                "display_name": "An OpenAlex-only record",
                "authorships": [],
                "publication_year": 2022,
                "publication_date": "2022-01-01",
                "primary_location": None,
                "type": "article",
                "cited_by_count": 2,
            },
        ],
    }


def test_crossref_openalex_search_deduplicates_and_persists(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["User-Agent"].startswith("Nexus-AI-PC/")
        assert request.headers["Accept"] == "application/json"
        timeout = request.extensions["timeout"]
        assert timeout["connect"] == 5.0
        assert timeout["read"] == 15.0
        if request.url.host == "api.crossref.org":
            assert request.url.params["query.bibliographic"] == "retrieval practice"
            assert request.url.params["rows"] == "5"
            return httpx.Response(200, json=_crossref_payload())
        if request.url.host == "api.openalex.org":
            assert request.url.params["search"] == "retrieval practice"
            assert request.url.params["per-page"] == "5"
            return httpx.Response(200, json=_openalex_payload())
        raise AssertionError(f"Unexpected request: {request.url}")

    database_path = tmp_path / "research.sqlite3"
    app = create_app(
        database_path,
        serve_static=False,
        research_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        project_id = _create_project(client)
        response = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retrieval practice", "limit": 5},
        )

        assert response.status_code == 201
        result = response.json()
        assert result["search"]["providers"] == ["crossref", "openalex"]
        assert result["search"]["result_count"] == 3
        assert len(result["papers"]) == 3
        shared = next(paper for paper in result["papers"] if paper["doi"] == "10.1000/shared")
        assert shared["providers"] == ["crossref", "openalex"]
        assert shared["citation_count"] == 12
        assert shared["authors"] == ["Ada Lovelace", "Grace Hopper"]
        assert shared["abstract"] == "Practice improves long-term retention."
        assert shared["publication_date"] == "2024-02-03"
        assert "canonical_key" not in shared

        search_id = result["search"]["id"]
        detail = client.get(f"/api/research/searches/{search_id}")
        assert detail.status_code == 200
        assert detail.json() == result
        runs = client.get(f"/api/research/projects/{project_id}/searches").json()
        assert runs == [result["search"]]

        repeated = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retrieval practice", "limit": 5},
        )
        assert repeated.status_code == 201
        database = client.app.state.database
        assert database.query_one("SELECT COUNT(*) AS count FROM research_search_runs")["count"] == 2
        assert database.query_one("SELECT COUNT(*) AS count FROM research_papers")["count"] == 3
        assert database.query_one("SELECT COUNT(*) AS count FROM research_paper_sources")["count"] == 4
        assert database.query_one("SELECT COUNT(*) AS count FROM research_search_results")["count"] == 6

    assert [request.url.host for request in requests] == [
        "api.crossref.org",
        "api.openalex.org",
        "api.crossref.org",
        "api.openalex.org",
    ]


def test_screening_decision_is_project_scoped_and_updatable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _crossref_payload() if request.url.host == "api.crossref.org" else _openalex_payload()
        return httpx.Response(200, json=payload)

    app = create_app(
        tmp_path / "screening.sqlite3",
        serve_static=False,
        research_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        project_id = _create_project(client)
        search = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retention"},
        ).json()
        paper_id = search["papers"][0]["id"]

        included = client.put(
            f"/api/research/projects/{project_id}/papers/{paper_id}/screening",
            json={"decision": "include", "reason": "Matches population and outcome."},
        )
        assert included.status_code == 200
        assert included.json()["decision"] == "include"

        changed = client.put(
            f"/api/research/projects/{project_id}/papers/{paper_id}/screening",
            json={"decision": "maybe", "reason": "Full text is needed."},
        )
        assert changed.status_code == 200
        assert changed.json()["decision"] == "maybe"
        decisions = client.get(f"/api/research/projects/{project_id}/screening").json()
        assert len(decisions) == 1
        assert decisions[0]["reason"] == "Full text is needed."

        detail = client.get(f"/api/research/searches/{search['search']['id']}").json()
        screened = next(paper for paper in detail["papers"] if paper["id"] == paper_id)
        assert screened["screening_decision"] == "maybe"

        other_project_id = client.post(
            "/api/research/projects",
            json={"name": "Other", "question": "Other question", "research_type": "review"},
        ).json()["id"]
        missing = client.put(
            f"/api/research/projects/{other_project_id}/papers/{paper_id}/screening",
            json={"decision": "exclude"},
        )
        assert missing.status_code == 404


def test_research_project_export_contains_reproducible_evidence(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _crossref_payload() if request.url.host == "api.crossref.org" else _openalex_payload()
        return httpx.Response(200, json=payload)

    app = create_app(
        tmp_path / "export.sqlite3",
        serve_static=False,
        research_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        project_id = _create_project(client)
        search = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retrieval practice", "limit": 5},
        ).json()
        paper_id = search["papers"][0]["id"]
        screened = client.put(
            f"/api/research/projects/{project_id}/papers/{paper_id}/screening",
            json={"decision": "include", "reason": "Matches population and outcome."},
        )
        assert screened.status_code == 200
        noted = client.post(
            f"/api/research/projects/{project_id}/notes",
            json={"body": "假设：检索练习能提高长期保持。"},
        )
        assert noted.status_code == 201

        exported = client.get(f"/api/research/projects/{project_id}/export")
        assert exported.status_code == 200
        payload = exported.json()
        markdown = payload["markdown"]
        assert "# 科研项目导出：Evidence review" in markdown
        assert "| 1 | `retrieval practice` | crossref + openalex |" in markdown
        assert "https://doi.org/10.1000/shared" in markdown
        assert "Retrieval practice and durable learning" in markdown
        assert "纳入" in markdown
        assert "Matches population and outcome." in markdown
        assert "假设：检索练习能提高长期保持。" in markdown
        assert "## 2. 证据表（全部候选文献）" in markdown
        assert "## 4. 研究日志" in markdown
        assert payload["generated_at"]

        audit = client.app.state.database.query_all(
            "SELECT * FROM audit_events WHERE category = 'research' AND action = 'export_project'"
        )
        assert len(audit) == 1
        assert audit[0]["target"] == str(project_id)

        missing = client.get("/api/research/projects/9999/export")
        assert missing.status_code == 404


def test_upstream_http_error_leaves_no_partial_search_data(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, json=_crossref_payload())
        return httpx.Response(503, text="private upstream response must not escape")

    app = create_app(
        tmp_path / "failed.sqlite3",
        serve_static=False,
        research_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        project_id = _create_project(client)
        response = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retention"},
        )
        assert response.status_code == 502
        assert response.json() == {
            "detail": "OpenAlex returned HTTP 503. Try the search again later."
        }
        assert "private upstream" not in response.text
        database = client.app.state.database
        for table in ("research_search_runs", "research_papers", "research_search_results"):
            assert database.query_one(f"SELECT COUNT(*) AS count FROM {table}")["count"] == 0


def test_timeout_and_unknown_project_do_not_write_or_make_extra_requests(tmp_path: Path) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("simulated timeout", request=request)

    app = create_app(
        tmp_path / "timeout.sqlite3",
        serve_static=False,
        research_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        project_id = _create_project(client)
        timeout = client.post(
            f"/api/research/projects/{project_id}/searches",
            json={"query": "retention"},
        )
        assert timeout.status_code == 504
        assert timeout.json() == {
            "detail": "Crossref timed out. Try the search again later."
        }
        assert request_count == 1

        unknown = client.post(
            "/api/research/projects/9999/searches",
            json={"query": "must not reach the network"},
        )
        assert unknown.status_code == 404
        assert request_count == 1
        assert client.app.state.database.query_one(
            "SELECT COUNT(*) AS count FROM research_search_runs"
        )["count"] == 0


def test_doi_normalization_is_case_insensitive_and_rejects_non_doi() -> None:
    assert normalize_doi(" DOI: 10.1234/ABC.Def ") == "10.1234/abc.def"
    assert normalize_doi("https://doi.org/10.5555%2FExample") == "10.5555/example"
    assert normalize_doi("https://example.test/not-a-doi") is None


def test_openalex_natural_language_question_does_not_become_wildcard_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"items": []}})
        assert request.url.params["search"] == "Does spaced repetition improve mathematics learning"
        return httpx.Response(200, json={"results": []})

    client = LiteratureClient(transport=httpx.MockTransport(handler))
    try:
        assert client.search("Does spaced repetition improve mathematics learning?", limit=5) == []
    finally:
        client.close()


def test_literature_client_rejects_redirects() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://untrusted.example/works"})

    client = LiteratureClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchUpstreamError) as raised:
            client.search("retrieval practice", limit=5)
    finally:
        client.close()

    assert raised.value.provider == "Crossref"
    assert raised.value.detail == "Crossref returned HTTP 302. Try the search again later."
    assert len(requests) == 1
