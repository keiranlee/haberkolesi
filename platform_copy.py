"""Application copy budgets and validation shared by generation and editing."""

LIMITS = {"x": 240, "threads": 480, "instagram": 1800}


def validate_platform_texts(texts):
    if set(texts) != set(LIMITS):
        raise ValueError("X, Threads ve Instagram metinlerinin üçü de gerekli")
    for platform, limit in LIMITS.items():
        if not isinstance(texts[platform], str) or not texts[platform].strip():
            raise ValueError(f"{platform} metni boş olamaz")
        if len(texts[platform]) > limit:
            raise ValueError(f"{platform} metni {limit} karakteri aşamaz")
    return {key: value.strip() for key, value in texts.items()}
