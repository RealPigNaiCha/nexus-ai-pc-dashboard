from backend.web_search import _safe_result_url


def test_web_result_url_rejects_local_and_credentialed_targets() -> None:
    assert _safe_result_url("http://127.0.0.1/private") is None
    assert _safe_result_url("http://localhost/private") is None
    assert _safe_result_url("https://user:pass@example.com/private") is None
    assert _safe_result_url("file:///etc/passwd") is None


def test_web_result_url_accepts_public_http_urls() -> None:
    assert _safe_result_url("https://example.com/research?q=ocr") == "https://example.com/research?q=ocr"
