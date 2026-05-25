def test_build_classifier_system_prompt_includes_rules_and_taxonomies():
    from scraper.agents.prompts.builder import build_classifier_system_prompt

    prompt = build_classifier_system_prompt(
        rules_md="# My Rules\n- rule 1",
        few_shot_examples=[],
    )
    assert "# My Rules" in prompt
    assert "Mercados Públicos - Variable" in prompt
    assert "Perú" in prompt
    assert "US Large Cap" in prompt


def test_build_classifier_system_prompt_includes_few_shot():
    from scraper.agents.prompts.builder import build_classifier_system_prompt

    example = {
        "producto": "Test Fondo",
        "input_text": "Producto: Test Fondo\nAdministrador: X",
        "expected_output": {
            "producto": "Test Fondo",
            "attributes": {},
            "global_confidence": 1.0,
            "unknowns": [],
        },
    }
    prompt = build_classifier_system_prompt(
        rules_md="# Rules",
        few_shot_examples=[example],
    )
    assert "Test Fondo" in prompt


def test_build_classifier_cache_blocks():
    from scraper.agents.prompts.builder import build_classifier_system_blocks

    blocks = build_classifier_system_blocks(rules_md="# Rules", few_shot_examples=[])
    assert isinstance(blocks, list)
    assert all("type" in b and b["type"] == "text" for b in blocks)
    assert any("cache_control" in b for b in blocks)


async def test_build_few_shot_from_db(seeded_and_split_session):
    from scraper.agents.prompts.builder import build_few_shot_from_db

    examples = await build_few_shot_from_db(seeded_and_split_session, limit=5)
    assert len(examples) == 5
    assert all("producto" in e for e in examples)
    assert all("input_text" in e for e in examples)
    assert all("expected_output" in e for e in examples)
