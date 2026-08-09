import pytest

from backend.chat_actions import auto_web_search_query, extract_web_search_query, parse_chat_actions


@pytest.mark.parametrize(
    ("message", "title", "project"),
    [
        ("创建任务：为 OCR 检索增加基准测试", "为 OCR 检索增加基准测试", "Nexus AI-PC"),
        ("帮我新建一个任务，检查第 82 页公式识别", "检查第 82 页公式识别", "Nexus AI-PC"),
        ("记录开发任务：修复搜索，项目：资料库", "修复搜索", "资料库"),
    ],
)
def test_parse_explicit_task_creation(message: str, title: str, project: str) -> None:
    actions = parse_chat_actions(message)

    assert len(actions) == 1
    assert actions[0].action == "create_agent_task"
    assert actions[0].title == title
    assert actions[0].project == project


def test_parse_explicit_progress_update() -> None:
    actions = parse_chat_actions("把任务 #12 的进度更新为 60%，备注：OCR 已完成")

    assert len(actions) == 1
    assert actions[0].action == "update_task_progress"
    assert actions[0].task_id == 12
    assert actions[0].progress_percent == 60
    assert actions[0].progress_note == "OCR 已完成"


@pytest.mark.parametrize(
    "message",
    [
        "如何创建任务？",
        "请解释‘创建任务：修复索引’这句话",
        "系统是否支持更新任务进度？",
        "任务 #12 的进度是多少？",
    ],
)
def test_parser_does_not_execute_discussion_or_questions(message: str) -> None:
    assert parse_chat_actions(message) == []


@pytest.mark.parametrize(
    ("message", "query"),
    [
        ("联网搜索 RapidOCR 最近版本", "RapidOCR 最近版本"),
        ("请网上查一下 OCR PDF 保留原页证据", "OCR PDF 保留原页证据"),
        ("搜索网络：DDGS Python", "DDGS Python"),
    ],
)
def test_extract_explicit_web_search_query(message: str, query: str) -> None:
    assert extract_web_search_query(message) == query


def test_web_search_discussion_does_not_trigger_network() -> None:
    assert extract_web_search_query("你可以联网搜索吗？") is None


def test_auto_web_search_is_selective_and_privacy_aware() -> None:
    assert auto_web_search_query("截至今年，这个研究结论是否有新证据？") is not None
    assert auto_web_search_query("解释本地资料里的定义") is None
    assert auto_web_search_query(r"检查 C:\AI-PC\private\notes.txt 的最新内容") is None
    assert auto_web_search_query("查证这个争议", local_evidence_count=2) is None
