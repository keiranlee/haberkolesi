"""Application copy budgets and validation shared by generation and editing."""

LIMITS = {"x": 280, "threads": 500, "instagram": 1800}
BLOG_LIMITS = {"blog_title": 160, "blog_description": 170, "blog_text": 14000}
BLOG_EN_LIMITS = {"blog_title_en": 160, "blog_description_en": 170, "blog_text_en": 14000}
FOLLOWUP_LIMITS = {"x_followups": (280, 3), "threads_followups": (500, 2)}


def validate_platform_texts(texts):
    if not set(LIMITS).issubset(texts) or set(texts) - set(LIMITS) - set(BLOG_LIMITS) - set(BLOG_EN_LIMITS) - set(FOLLOWUP_LIMITS):
        raise ValueError("X, Threads ve Instagram metinlerinin üçü de gerekli")
    for platform, limit in LIMITS.items():
        if not isinstance(texts[platform], str) or not texts[platform].strip():
            raise ValueError(f"{platform} metni boş olamaz")
        if len(texts[platform]) > limit:
            raise ValueError(f"{platform} metni {limit} karakteri aşamaz")
    for group in (BLOG_LIMITS, BLOG_EN_LIMITS):
        present_blog = set(group).intersection(texts)
        if present_blog and present_blog != set(group):
            raise ValueError("Her dilde blog başlığı, açıklaması ve metni birlikte gerekli")
        for field in present_blog:
            if not isinstance(texts[field], str) or not texts[field].strip():
                raise ValueError(f"{field} boş olamaz")
            if len(texts[field]) > group[field]:
                raise ValueError(f"{field} en fazla {group[field]} karakter olabilir")
    for field, (limit, max_posts) in FOLLOWUP_LIMITS.items():
        if field not in texts:
            continue
        if not isinstance(texts[field], str) or not texts[field].strip():
            raise ValueError(f"{field} boş olamaz")
        posts = split_followups(texts[field])
        if len(posts) > max_posts or any(len(post) > limit for post in posts):
            raise ValueError(f"{field}: en fazla {max_posts} devam gönderisi, her biri en fazla {limit} karakter olabilir")
    return {key: value.strip() for key, value in texts.items()}


def content_pack(result):
    """Keep legacy outputs readable while persisting new blog fields together."""
    fields = {"x": result.text, "threads": getattr(result, "threads_text", None), "instagram": getattr(result, "instagram_text", None)}
    for group in (BLOG_LIMITS, BLOG_EN_LIMITS):
        blog = {name: getattr(result, name, None) for name in group}
        if all(blog.values()):
            fields.update(blog)
    for name in FOLLOWUP_LIMITS:
        if getattr(result, name, None):
            fields[name] = getattr(result, name)
    return fields


def split_followups(text):
    import re
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
