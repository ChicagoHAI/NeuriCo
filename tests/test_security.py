from core.security import sanitize_text


def test_redacts_google_oauth_access_token():
    token = "ya29." + "A" * 30
    assert sanitize_text(token) == "[REDACTED_GOOGLE_OAUTH_ACCESS]"


def test_redacts_google_oauth_refresh_token():
    token = "1//0" + "A" * 30
    assert sanitize_text(token) == "[REDACTED_GOOGLE_OAUTH_REFRESH]"


def test_redacts_google_oauth_tokens_embedded_in_log_text():
    access = "ya29." + "A" * 30
    refresh = "1//0" + "B" * 30

    text = f"access_token={access} refresh_token={refresh}"

    sanitized = sanitize_text(text)

    assert access not in sanitized
    assert refresh not in sanitized
    assert "[REDACTED_GOOGLE_OAUTH_ACCESS]" in sanitized
    assert "[REDACTED_GOOGLE_OAUTH_REFRESH]" in sanitized


def test_does_not_redact_short_google_oauth_like_strings():
    text = "ya29.short 1//0short"
    assert sanitize_text(text) == text