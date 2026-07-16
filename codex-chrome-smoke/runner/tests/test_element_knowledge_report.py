import json

from runner import element_knowledge_report


def sample_library():
    return {
        "refreshed_at": "2026-07-09T00:00:00Z",
        "pages": [{"page_id": "users"}],
        "elements": [
            {
                "element_id": "users.create_button",
                "name": "create_button",
                "execution_count": 4,
                "failed_count": 2,
                "success_rate": 0.5,
                "healing_issue": "target_not_visible",
                "healing_suggestion": "Scroll the element into view before retrying.",
                "last_error": "Agent target is not visible",
            },
            {
                "element_id": "users.search_input",
                "name": "search_input",
                "execution_count": 3,
                "failed_count": 0,
                "success_rate": 1.0,
            },
        ],
    }


def test_failure_hotspots_prioritizes_failed_elements():
    hotspots = element_knowledge_report.failure_hotspots(sample_library())

    assert hotspots[0]["element_id"] == "users.create_button"
    assert hotspots[0]["healing_issue"] == "target_not_visible"


def test_build_report_model_uses_summary_and_library():
    model = element_knowledge_report.build_report_model(
        sample_library(),
        {
            "refreshed_at": "2026-07-09T01:00:00Z",
            "source": "library.json",
            "output_path": "out.json",
            "page_count": 1,
            "element_count": 2,
            "feedback_record_count": 7,
            "healing_suggestion_count": 1,
        },
    )

    assert model["element_count"] == 2
    assert model["feedback_record_count"] == 7
    assert model["healing_suggestion_count"] == 1
    assert model["hotspots"][0]["element_id"] == "users.create_button"


def test_render_markdown_report_contains_summary_and_hotspot():
    model = element_knowledge_report.build_report_model(sample_library(), {"feedback_record_count": 7})

    markdown = element_knowledge_report.render_markdown_report(model)

    assert "# Element Knowledge Refresh Report" in markdown
    assert "feedback_record_count: 7" in markdown
    assert "users.create_button" in markdown
    assert "target_not_visible" in markdown


def test_reports_list_canvas_and_iframe_regions_not_dom_scanned():
    library = sample_library()
    library["pages"] = [
        {
            "page_id": "screen_wall",
            "name": "Screen wall",
            "unscannable_regions": [
                {"kind": "canvas", "reason": "canvas_visual_surface_not_dom_scanned", "selector": "canvas:nth-of-type(1)", "label": "mine-canvas"},
                {"kind": "iframe", "reason": "cross_origin_or_unavailable_iframe", "selector": "iframe:nth-of-type(1)", "label": "remote"},
            ],
        }
    ]

    model = element_knowledge_report.build_report_model(library, {})
    markdown = element_knowledge_report.render_markdown_report(model)
    html = element_knowledge_report.render_html_report(model)

    assert len(model["unscannable_regions"]) == 2
    assert "Areas Not DOM Scanned" in markdown
    assert "canvas_visual_surface_not_dom_scanned" in markdown
    assert "cross_origin_or_unavailable_iframe" in html


def test_render_html_report_escapes_content():
    library = sample_library()
    library["elements"][0]["last_error"] = "<script>alert(1)</script>"
    model = element_knowledge_report.build_report_model(library, {})

    html = element_knowledge_report.render_html_report(model)

    assert "Element Knowledge Refresh Report" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_write_element_knowledge_reports_writes_markdown_and_html(tmp_path):
    library_path = tmp_path / "library.json"
    summary_path = tmp_path / "summary.json"
    markdown_path = tmp_path / "report.md"
    html_path = tmp_path / "report.html"
    library_path.write_text(json.dumps(sample_library(), ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps({"feedback_record_count": 7}, ensure_ascii=False), encoding="utf-8")

    paths = element_knowledge_report.write_element_knowledge_reports(
        library_path=library_path,
        summary_path=summary_path,
        markdown_path=markdown_path,
        html_path=html_path,
    )

    assert paths == {"markdown_report_path": str(markdown_path), "html_report_path": str(html_path)}
    assert "users.create_button" in markdown_path.read_text(encoding="utf-8")
    assert "Failure Hotspots" in html_path.read_text(encoding="utf-8")
