LIKE_ESCAPE = "\\"


def contains_pattern(term: str) -> str:
    """A lower-cased `%term%` LIKE pattern with the user's own `\\`, `%` and
    `_` escaped, for use with `.like(pattern, escape=LIKE_ESCAPE)`.

    E2E Validation Phase 10 — customer search interpolated the raw term, so
    a query of "%" matched every restaurant/product/category and "_" any
    single character."""
    escaped = term.strip().lower().replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
