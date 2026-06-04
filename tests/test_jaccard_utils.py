"""Unit tests for Jaccard tokenize/similarity logic (AA-121)."""
import re


def tokenize(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def jaccard(text_a: str, text_b: str) -> float:
    a, b = tokenize(text_a), tokenize(text_b)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def test_jaccard_identical():
    assert jaccard("hello world", "hello world") == 1.0


def test_jaccard_disjoint():
    assert jaccard("hello world", "foo bar") == 0.0


def test_jaccard_partial():
    # tokens: "hello world foo" → {hello, world, foo}
    # tokens: "hello bar foo"   → {hello, bar, foo}
    # intersection = {hello, foo} = 2, union = {hello, world, foo, bar} = 4
    result = jaccard("hello world foo", "hello bar foo")
    assert result == 0.5


def test_jaccard_case_insensitive():
    assert jaccard("Hello", "hello") == 1.0


def test_tokenize_strips_punctuation():
    assert tokenize("hello, world!") == {"hello", "world"}
