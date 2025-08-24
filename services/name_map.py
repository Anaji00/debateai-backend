# services/name_map.py

# Alias <-> Canonical mapping (expand as you add characters)

ALIAS_TO_CANON = {
    "the titan": "thanos",
    "thanos": "thanos",

    "the businessman": "donald trump",
    "trump": "donald trump",
    "donald trump": "donald trump",
}

CANON_TO_ALIAS = {
    "thanos": "the titan",
    "the titan": "the titan",

    "donald trump": "the businessman",
    "trump": "the businessman",
    "the businessman": "the businessman",
}

def to_canonical(name: str) -> str:
    if not name:
        return name
    key = name.strip().lower()
    return ALIAS_TO_CANON.get(key, name)

def to_alias(name: str) -> str:
    if not name:
        return name
    key = name.strip().lower()
    return CANON_TO_ALIAS.get(key, key)
