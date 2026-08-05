import pytest

from langparse.services.parse_service import ENGINE_MAP, ParseService


def test_unimplemented_engines_are_not_offered_as_available():
    assert "vision_llm" not in ENGINE_MAP
    assert "paddle" not in ENGINE_MAP


def test_deepdoc_is_offered_as_available():
    assert "deepdoc" in ENGINE_MAP


def test_selecting_an_unimplemented_engine_says_so_before_any_work():
    with pytest.raises(ValueError, match="not implemented yet"):
        ParseService().create_engine("vision_llm")


def test_the_error_lists_what_can_actually_be_used():
    with pytest.raises(ValueError, match="simple"):
        ParseService().create_engine("paddle")


def test_an_unknown_engine_is_still_reported_as_unknown():
    with pytest.raises(ValueError, match="Unknown engine"):
        ParseService().create_engine("nonexistent")
