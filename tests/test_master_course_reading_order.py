from scripts.build_master_ai_course import collect_dir


def test_master_course_uses_declared_teaching_order_and_keeps_extra_material(tmp_path):
    chapter = tmp_path / "chapter"
    chapter.mkdir()
    sources = {
        "index.md": "# Introduction\n```toc\n:maxdepth: 2\n\nz_basics\na_advanced\nz_basics\n```\n",
        "a_advanced.md": "# Advanced\nOnly after the basics.\n",
        "z_basics.md": "# Basics\nStart here.\n",
        "extra.md": "# Extra\nPreserved supplementary material.\n",
        "extra_origin.md": "A duplicate export.\n",
    }
    for name, text in sources.items():
        (chapter / name).write_text(text, encoding="utf-8")
    content, provenance = collect_dir(tmp_path, "chapter")
    assert provenance.split(";") == ["chapter/index.md", "chapter/z_basics.md", "chapter/a_advanced.md", "chapter/extra.md"]
    assert content.index("# Introduction") < content.index("# Basics") < content.index("# Advanced")
    assert content.count("# Basics") == 1
    assert "Preserved supplementary material" in content
    assert "duplicate export" not in content


def test_master_course_without_toc_keeps_all_files_in_stable_order(tmp_path):
    chapter = tmp_path / "chapter"
    chapter.mkdir()
    for name in ["b.md", "a.md"]:
        (chapter / name).write_text(name, encoding="utf-8")
    content, provenance = collect_dir(tmp_path, "chapter")
    assert provenance == "chapter/a.md;chapter/b.md"
    assert content.index("a.md") < content.index("b.md")
