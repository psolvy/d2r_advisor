"""Web links for advice lines (runewords, crafts, items).

The URL template comes from config.yaml (`link_template`); {query} is replaced
with a URL-encoded search query. Default is a web search so it works for any
term; point it at your favorite database site if it supports search URLs.
"""
from urllib.parse import quote_plus

DEFAULT_TEMPLATE = "https://duckduckgo.com/?q={query}"
_template = DEFAULT_TEMPLATE


def configure(template):
    global _template
    if template and "{query}" in template:
        _template = template


def url(query):
    return _template.replace("{query}", quote_plus(query))


def runeword_url(name):
    return url(f"d2r runeword {name}")


def item_url(name):
    return url(f"d2r {name}")


def recipe_url(topic):
    return url(f"d2r {topic}")
