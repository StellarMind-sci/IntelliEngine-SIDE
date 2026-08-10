from __future__ import annotations


class RegexProfileError(ValueError):
    pass


_ESCAPABLE = frozenset(".*+?[](){}|^$\\")


class _Parser:
    def __init__(self, pattern: str, maximum_repeat: int) -> None:
        self.pattern = pattern
        self.maximum_repeat = maximum_repeat
        self.position = 0
        self.nodes = 0

    def parse(self) -> int:
        self._alternation(in_group=False)
        if self.position != len(self.pattern):
            raise RegexProfileError("unexpected token")
        # The compact-counter representation includes the pattern root.
        return self.nodes + 1

    def _alternation(self, in_group: bool) -> tuple[bool, bool]:
        contains_alternation = False
        contains_quantifier = False
        contains_quantifier |= self._concatenation(in_group)
        while self._peek() == "|":
            contains_alternation = True
            self.nodes += 1
            self.position += 1
            contains_quantifier |= self._concatenation(in_group)
        return contains_alternation, contains_quantifier

    def _concatenation(self, in_group: bool) -> bool:
        seen = 0
        contains_quantifier = False
        while self.position < len(self.pattern) and self._peek() not in ")|":
            contains_quantifier |= self._atom(in_group)
            seen += 1
        if seen > 1:
            self.nodes += 1
        return contains_quantifier

    def _atom(self, in_group: bool) -> bool:
        character = self._peek()
        group_complex = False
        if character == "\\":
            self.position += 1
            if self.position >= len(self.pattern) or self._peek() not in _ESCAPABLE:
                raise RegexProfileError("implementation-private escape")
            self.position += 1
            self.nodes += 1
        elif character == "(":
            if self.pattern.startswith("(?", self.position):
                raise RegexProfileError("special groups are forbidden")
            self.position += 1
            has_alternation, has_quantifier = self._alternation(in_group=True)
            if self._peek() != ")":
                raise RegexProfileError("unclosed group")
            self.position += 1
            self.nodes += 1
            group_complex = has_alternation or has_quantifier
        elif character == "[":
            self._character_class()
        elif character in ".^$":
            self.position += 1
            self.nodes += 1
        elif character in "*+?{}]":
            raise RegexProfileError("quantifier or delimiter without atom")
        else:
            self.position += 1
            self.nodes += 1
        if self.position < len(self.pattern) and self._peek() in "*+?{":
            if group_complex:
                raise RegexProfileError("complex quantified group")
            self._quantifier()
            self.nodes += 1
            if self.position < len(self.pattern) and self._peek() in "?+":
                raise RegexProfileError("non-greedy or possessive quantifier")
            return True
        return False

    def _character_class(self) -> None:
        self.position += 1
        if self._peek() == "^":
            self.position += 1
        items = 0
        while self.position < len(self.pattern) and self._peek() != "]":
            if self._peek() == "\\":
                self.position += 1
                if self.position >= len(self.pattern) or self._peek() not in _ESCAPABLE:
                    raise RegexProfileError("implementation-private escape")
            self.position += 1
            if self.position < len(self.pattern) - 1 and self._peek() == "-" and self.pattern[self.position + 1] != "]":
                self.position += 2
                self.nodes += 1
            items += 1
        if self._peek() != "]" or items == 0:
            raise RegexProfileError("invalid character class")
        self.position += 1
        self.nodes += 1

    def _quantifier(self) -> None:
        character = self._peek()
        if character in "*+?":
            self.position += 1
            return
        end = self.pattern.find("}", self.position + 1)
        if end < 0:
            raise RegexProfileError("unclosed bounded repeat")
        body = self.pattern[self.position + 1 : end]
        parts = body.split(",")
        if len(parts) not in (1, 2) or any(not part.isascii() or not part.isdigit() for part in parts):
            raise RegexProfileError("invalid bounded repeat")
        minimum = int(parts[0])
        maximum = int(parts[-1])
        if minimum > maximum or maximum > self.maximum_repeat:
            raise RegexProfileError("bounded repeat outside limits")
        self.position = end + 1

    def _peek(self) -> str:
        return self.pattern[self.position] if self.position < len(self.pattern) else ""


def parse_pattern(pattern: str, maximum_repeat: int, maximum_scalars: int = 1024) -> int:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in pattern):
        raise RegexProfileError("pattern is not Unicode scalar text")
    if len(pattern) > maximum_scalars:
        raise RegexProfileError("pattern exceeds scalar limit")
    return _Parser(pattern, maximum_repeat).parse()
