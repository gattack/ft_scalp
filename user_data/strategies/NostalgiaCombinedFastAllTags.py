from NostalgiaCombinedFast import NostalgiaCombinedFast


class NostalgiaCombinedFastAllTags(NostalgiaCombinedFast):
    """
    CombinedFast variant that allows all declared *_mode_tags from child strategies.

    This inherits:
    - signal_learning support
    - force_tag_1_fallback
    - wrapper lifecycle fixes
    """

    def _collect_mode_tags(self, strat, side_prefix: str) -> set[str]:
        tags: set[str] = set()
        for attr_name in dir(strat):
            if not (attr_name.startswith(side_prefix) and attr_name.endswith("_mode_tags")):
                continue
            try:
                value = getattr(strat, attr_name)
            except Exception:
                continue
            if isinstance(value, list):
                for tag in value:
                    if tag is not None:
                        for token in self._tag_tokens(str(tag)):
                            tags.add(token)
        return tags
