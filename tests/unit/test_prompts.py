from services.content_generation.prompts import build_rewrite_prompt

def test_prompt_contains_tour_name():
    tour = {"name": "Halong Bay Cruise", "country": "Vietnam", "summary": "Beautiful bay"}
    seo  = {"keywords": {"top_keywords": ["vietnam cruise"]}, "people_also_ask": []}
    prompt = build_rewrite_prompt(tour, seo)
    assert "Halong Bay Cruise" in prompt
    assert "vietnam cruise" in prompt

def test_prompt_contains_few_shots():
    tour = {"name": "Tour A", "country": "Thailand"}
    seo  = {}
    few_shots = [{"input": "old content", "output": "refined content"}]
    prompt = build_rewrite_prompt(tour, seo, few_shots)
    assert "EXAMPLES FOR REFERENCE" in prompt
    assert "refined content" in prompt

def test_prompt_no_few_shots():
    tour = {"name": "Tour B", "country": "Japan"}
    seo  = {}
    prompt = build_rewrite_prompt(tour, seo)
    assert "EXAMPLES FOR REFERENCE" not in prompt

def test_prompt_contains_paa():
    tour = {"name": "Tour C", "country": "Cambodia"}
    seo  = {
        "keywords": {},
        "people_also_ask": ["Is Angkor Wat worth visiting?", "Best time for Cambodia?"]
    }
    prompt = build_rewrite_prompt(tour, seo)
    assert "Is Angkor Wat worth visiting?" in prompt
