"""Versioned synthetic tasks. Tests are public; this is not a hidden-test eval."""

from dataclasses import dataclass
from textwrap import dedent

SUITE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    spec: str
    starter: str
    reference: str
    checks: tuple[str, ...]


def code(source: str) -> str:
    return dedent(source).strip() + "\n"


TASKS = (
    Task(
        "mean",
        "bugfix",
        "Implement mean(values). Return the arithmetic mean; raise ValueError for empty input.",
        "def mean(values):\n    return sum(values) // len(values)\n",
        code("""
            def mean(values):
                if not values:
                    raise ValueError("empty input")
                return sum(values) / len(values)
        """),
        (
            "self.assertEqual(mean([1, 2]), 1.5)",
            "self.assertEqual(mean([-3, 1]), -1)",
            "self.assertEqual(mean([0]), 0)",
            "with self.assertRaises(ValueError): mean([])",
        ),
    ),
    Task(
        "chunk",
        "implementation",
        "chunk(items, size) returns list chunks preserving order, including the final partial "
        "chunk. Empty items returns []; size <= 0 raises ValueError.",
        "def chunk(items, size):\n    raise NotImplementedError\n",
        code("""
            def chunk(items, size):
                if size <= 0:
                    raise ValueError("size must be positive")
                return [items[i:i + size] for i in range(0, len(items), size)]
        """),
        (
            "self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])",
            "self.assertEqual(chunk([], 2), [])",
            "self.assertEqual(chunk([1], 5), [[1]])",
            "with self.assertRaises(ValueError): chunk([1], 0)",
            "with self.assertRaises(ValueError): chunk([], -1)",
        ),
    ),
    Task(
        "deduplicate",
        "refactor",
        "Refactor deduplicate(items) to preserve first-occurrence order and support hashable "
        "items in expected O(n) time. Return a new list.",
        "def deduplicate(items):\n    return sorted(set(items))\n",
        code("""
            def deduplicate(items):
                return list(dict.fromkeys(items))
        """),
        (
            "self.assertEqual(deduplicate([3, 1, 3, 2, 1]), [3, 1, 2])",
            "self.assertEqual(deduplicate([]), [])",
            "self.assertEqual(deduplicate(['b', 'a', 'b']), ['b', 'a'])",
            "items = [1, 1]; deduplicate(items); self.assertEqual(items, [1, 1])",
        ),
    ),
    Task(
        "balanced",
        "bugfix",
        "balanced(text) returns whether (), [], {} are properly nested. Ignore other characters.",
        "def balanced(text):\n    return text.count('(') == text.count(')')\n",
        code("""
            def balanced(text):
                pairs = {')': '(', ']': '[', '}': '{'}
                stack = []
                for char in text:
                    if char in '([{':
                        stack.append(char)
                    elif char in pairs:
                        if not stack or stack.pop() != pairs[char]:
                            return False
                return not stack
        """),
        (
            "self.assertTrue(balanced('a{b[c](d)}'))",
            "self.assertTrue(balanced(''))",
            "self.assertFalse(balanced(')('))",
            "self.assertFalse(balanced('([)]'))",
            "self.assertFalse(balanced('['))",
        ),
    ),
    Task(
        "merge_intervals",
        "implementation",
        "merge_intervals(intervals) merges overlapping or touching [start, end] integer "
        "intervals; return sorted lists and do not mutate the input. Assume start <= end.",
        "def merge_intervals(intervals):\n    return intervals\n",
        code("""
            def merge_intervals(intervals):
                merged = []
                for start, end in sorted(intervals):
                    if merged and start <= merged[-1][1]:
                        merged[-1][1] = max(merged[-1][1], end)
                    else:
                        merged.append([start, end])
                return merged
        """),
        (
            "self.assertEqual(merge_intervals([[4, 8], [1, 4], [10, 11]]), [[1, 8], [10, 11]])",
            "self.assertEqual(merge_intervals([[1, 9], [2, 3]]), [[1, 9]])",
            "self.assertEqual(merge_intervals([]), [])",
            "x = [[3, 4], [1, 3]]; merge_intervals(x); self.assertEqual(x, [[3, 4], [1, 3]])",
        ),
    ),
    Task(
        "word_counts",
        "refactor",
        "word_counts(text) counts case-insensitive ASCII words matching [a-z]+; "
        "ignore digits and punctuation and return a dict.",
        "def word_counts(text):\n    return {w: text.split().count(w) for w in text.split()}\n",
        code("""
            import re
            from collections import Counter
            def word_counts(text):
                return dict(Counter(re.findall(r'[a-z]+', text.lower())))
        """),
        (
            "self.assertEqual(word_counts('Hi, hi! BYE.'), {'hi': 2, 'bye': 1})",
            "self.assertEqual(word_counts('123 --'), {})",
            "self.assertEqual(word_counts('a1b a'), {'a': 2, 'b': 1})",
            "self.assertEqual(word_counts(''), {})",
        ),
    ),
    Task(
        "binary_search",
        "bugfix",
        "binary_search(items, target) returns the first matching index in a sorted integer "
        "list, or -1. Use logarithmic search.",
        code("""
            def binary_search(items, target):
                low, high = 0, len(items) - 1
                while low < high:
                    mid = (low + high) // 2
                    if items[mid] < target:
                        low = mid + 1
                    else:
                        high = mid
                return low
        """),
        code("""
            def binary_search(items, target):
                low, high = 0, len(items)
                while low < high:
                    mid = (low + high) // 2
                    if items[mid] < target:
                        low = mid + 1
                    else:
                        high = mid
                return low if low < len(items) and items[low] == target else -1
        """),
        (
            "self.assertEqual(binary_search([], 1), -1)",
            "self.assertEqual(binary_search([1, 2, 2, 2, 4], 2), 1)",
            "self.assertEqual(binary_search([1, 3], 2), -1)",
            "self.assertEqual(binary_search([1, 3], 4), -1)",
            "self.assertEqual(binary_search([1, 3], 3), 1)",
        ),
    ),
    Task(
        "flatten",
        "implementation",
        "flatten(items) recursively flattens nested lists only; preserve tuples, strings, "
        "and other non-list values as atomic values. Return a list.",
        "def flatten(items):\n    return list(items)\n",
        code("""
            def flatten(items):
                result = []
                for item in items:
                    if isinstance(item, list):
                        result.extend(flatten(item))
                    else:
                        result.append(item)
                return result
        """),
        (
            "self.assertEqual(flatten([1, [2, [3]], []]), [1, 2, 3])",
            "self.assertEqual(flatten(['ab', (1, 2), None]), ['ab', (1, 2), None])",
            "self.assertEqual(flatten([]), [])",
            "self.assertEqual(flatten([[[]]]), [])",
        ),
    ),
    Task(
        "rotate",
        "bugfix",
        "rotate(items, k) returns a new list rotated right by integer k. Negative k rotates "
        "left; handle empty lists and k larger than the length without mutating input.",
        "def rotate(items, k):\n    return items[-k:] + items[:-k]\n",
        code("""
            def rotate(items, k):
                if not items:
                    return []
                k %= len(items)
                return items[-k:] + items[:-k] if k else items[:]
        """),
        (
            "self.assertEqual(rotate([1, 2, 3], 4), [3, 1, 2])",
            "self.assertEqual(rotate([1, 2, 3], -4), [2, 3, 1])",
            "self.assertEqual(rotate([], 9), [])",
            "x = [1, 2]; y = rotate(x, 0); self.assertEqual(y, x); self.assertIsNot(y, x)",
        ),
    ),
    Task(
        "group_records",
        "refactor",
        "group_records(records, key) returns a dict grouping dict records by their key value. "
        "Use None when missing; preserve record order in each group. Do not mutate input.",
        code("""
            def group_records(records, key):
                result = {}
                for record in records:
                    result[record[key]] = [record]
                return result
        """),
        code("""
            def group_records(records, key):
                result = {}
                for record in records:
                    result.setdefault(record.get(key), []).append(record)
                return result
        """),
        (
            "self.assertEqual(group_records([{'a': 1}, {'a': 1, 'b': 2}], 'a'), "
            "{1: [{'a': 1}, {'a': 1, 'b': 2}]})",
            "self.assertEqual(group_records([{}, {'a': None}], 'a'), {None: [{}, {'a': None}]})",
            "self.assertEqual(group_records([], 'x'), {})",
            "x = [{'a': 1}]; group_records(x, 'a'); self.assertEqual(x, [{'a': 1}])",
        ),
    ),
)
