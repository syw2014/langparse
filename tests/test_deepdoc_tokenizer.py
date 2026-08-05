from langparse.engines.pdf.deepdoc.tokenizer import is_chinese, tag, tokenize


def test_is_chinese_true_for_cjk_char():
    assert is_chinese("中") is True


def test_is_chinese_false_for_latin_char():
    assert is_chinese("A") is False


def test_is_chinese_false_for_empty_string():
    assert is_chinese("") is False


def test_tokenize_splits_english_text_on_whitespace():
    assert tokenize("hello world").split() == ["hello", "world"]


def test_tokenize_returns_a_space_joined_string():
    result = tokenize("北京欢迎你")
    assert isinstance(result, str)
    assert len(result.split()) >= 1


def test_tag_returns_a_pos_tag_string_for_a_word():
    result = tag("北京")
    assert isinstance(result, str)
    assert result


def test_tag_empty_string_returns_empty_string():
    assert tag("") == ""
