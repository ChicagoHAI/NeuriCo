"""Writing rules the ideation stages must satisfy, checked in code.

Word caps per field, prose hygiene (no knowledge-base ids, file names or pipeline talk in text a
reader sees), repeated passages across methods, and a reading-level estimate. A violation is
returned as a message the agent can act on; the runtime's cross-checks raise so the factory's
retry feeds it back into the next prompt.

Ported from sai-review ``src/sai_digest/brief.py`` (the detail-stage subset; see
``NOTICE.md``), with the id regexes and pipeline words re-targeted at NeuriCo's vocabulary.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

SENTENCE_FLAG_WORDS = 30
FK_GRADE_MAX = 12.0
SHINGLE_WORDS = 20
SHINGLE_MIN_IDEAS = 3
TITLE_WORDS_MAX = 12

# Word caps on the stages' prose (the skills state the same numbers; the schemas' maxLength is
# the character backstop at about 8.4 characters per word).
DETAIL_CAPS: Dict[str, int] = {
    "problem.statement": 120, "problem.why_now": 120,
    "idea.hypothesis": 50, "idea.method": 250, "idea.expected_result": 60,
    "idea.method_steps[]": 25, "judge.distinctness": 25,
}
METHOD_STEPS_MIN, METHOD_STEPS_MAX = 3, 7

# What must not appear in prose a human reads: knowledge-base ids, workspace file names, pipeline words.
ID_RE = re.compile(r"\b(?:finding|run|result|inbox|idea|job|proposal|event|drift|arxiv|doi|hf|rss):"
                   r"[A-Za-z0-9][\w.:/-]*", re.I)
FILE_RE = re.compile(r"(?:\b(?:input|output|artifacts|schemas|tools)/[\w./-]+|\b[\w-]+\.(?:json|jsonl|md|yaml|py)\b)")
PIPELINE_WORDS = ("schema", "pipeline", "supplied findings", "finding id", "finding ids", "planner run",
                  "knowledge base", "kb tool", "input/", "output/", "registry")
PIPELINE_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in PIPELINE_WORDS) + r")", re.I)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-/.]*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_STOPWORDS = frozenset("""a an and are as at be by for from in is it its of on or that the this to
with we our use using used then than into over under each per all any not no vs via""".split())

# Ideas whose `method` texts overlap more than this (Jaccard over content tokens) are variants of
# one design, not distinct ideas.
IDEA_METHOD_JACCARD_MAX = 0.6


# --- text helpers ---------------------------------------------------------------------------

def words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


def sentences(text: str) -> List[str]:
    return [p.strip() for p in _SENT_SPLIT_RE.split((text or "").strip()) if p.strip()]


def count_syllables(word: str) -> int:
    """A small heuristic syllable counter (vowel groups, silent e, -le, -es/-ed)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith(("es", "ed")) and not w.endswith(("ses", "zes", "ted", "ded", "ies")) and n > 1:
        n -= 1
    return max(1, n)


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid grade level: 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59."""
    sents = sentences(text)
    ws = [w for w in words(text) if re.search(r"[a-zA-Z]", w)]
    if not sents or not ws:
        return 0.0
    syl = sum(count_syllables(part) for w in ws for part in w.split("-"))
    return round(0.39 * (len(ws) / len(sents)) + 11.8 * (syl / len(ws)) - 15.59, 2)


def long_sentences(text: str, limit: int = SENTENCE_FLAG_WORDS) -> List[str]:
    return [s for s in sentences(text) if word_count(s) > limit]


def shingles(text: str, n: int = SHINGLE_WORDS) -> Set[str]:
    ws = [w.lower() for w in words(text)]
    return {" ".join(ws[i:i + n]) for i in range(0, max(0, len(ws) - n + 1))}


def repeated_shingles(texts: Sequence[str], *, n: int = SHINGLE_WORDS, min_count: int = SHINGLE_MIN_IDEAS
                      ) -> List[Tuple[str, int]]:
    """``[(shingle, count)]`` for n-word shingles shared by ``min_count`` or more texts."""
    seen: Dict[str, int] = {}
    for t in texts:
        for s in shingles(t, n):
            seen[s] = seen.get(s, 0) + 1
    return sorted(((s, c) for s, c in seen.items() if c >= min_count), key=lambda x: (-x[1], x[0]))


def method_tokens(text: str) -> Set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3 and t not in _STOPWORDS}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def method_overlaps(ideas: Iterable[Dict[str, Any]], threshold: float = IDEA_METHOD_JACCARD_MAX
                    ) -> List[Tuple[str, str, float]]:
    """Pairs of ideas whose ``method`` texts overlap more than ``threshold``."""
    toks = [(i["id"], method_tokens(i.get("method", ""))) for i in ideas]
    out = []
    for a in range(len(toks)):
        for b in range(a + 1, len(toks)):
            j = jaccard(toks[a][1], toks[b][1])
            if j > threshold:
                out.append((toks[a][0], toks[b][0], round(j, 2)))
    return out


# --- checks ------------------------------------------------------------------------------------

def check_prose_hygiene(path: str, text: str) -> List[str]:
    """Ids, file names and pipeline words in one prose field."""
    out = []
    ids = ID_RE.findall(text or "")
    if ids:
        out.append(f"{path}: contains an internal id ({', '.join(sorted(set(ids))[:3])}); "
                   "name the thing (model, eval, lab, paper) and keep ids in the id fields")
    files = FILE_RE.findall(text or "")
    if files:
        out.append(f"{path}: contains a file name ({', '.join(sorted(set(files))[:3])})")
    pw = PIPELINE_RE.findall(text or "")
    if pw:
        out.append(f"{path}: contains pipeline talk ({', '.join(sorted({w.lower() for w in pw})[:3])}); "
                   "write for the reader, not the pipeline")
    return out


def check_title(path: str, title: str) -> List[str]:
    out = []
    n = word_count(title)
    if n > TITLE_WORDS_MAX:
        out.append(f"{path}: {n} words, cap {TITLE_WORDS_MAX}")
    if ":" in (title or ""):
        out.append(f"{path}: no colon-subtitles; a plain question or claim")
    return out


def check_detail_caps(stage_id: str, data: Dict[str, Any]) -> List[str]:
    """Word caps + prose hygiene for one stage's artifact. Returns the violations (empty = fine);
    the runtime raises so the retry feeds them back."""
    errs: List[str] = []
    if stage_id == "problem":
        errs += check_title("title", data.get("title", ""))
        for k in ("statement", "why_now"):
            n = word_count(data.get(k, ""))
            cap = DETAIL_CAPS[f"problem.{k}"]
            if n > cap:
                errs.append(f"{k}: {n} words, cap {cap}")
            errs += check_prose_hygiene(k, data.get(k, ""))
            grade = flesch_kincaid_grade(data.get(k, ""))
            if grade > FK_GRADE_MAX + 4:   # the hard stop; the softer target is in the skill
                errs.append(f"{k}: reading grade {grade}, keep sentences and words short (grade <= {FK_GRADE_MAX})")
    elif stage_id == "ideation":
        ideas = data.get("ideas") or []
        for idea in ideas:
            iid = idea.get("id", "?")
            errs += check_title(f"{iid}.title", idea.get("title", ""))
            for k in ("hypothesis", "method", "expected_result"):
                n = word_count(idea.get(k, ""))
                cap = DETAIL_CAPS[f"idea.{k}"]
                if n > cap:
                    errs.append(f"{iid}.{k}: {n} words, cap {cap}")
            errs += check_prose_hygiene(f"{iid}.hypothesis", idea.get("hypothesis", ""))
            steps = idea.get("method_steps")
            if not isinstance(steps, list) or not (METHOD_STEPS_MIN <= len(steps) <= METHOD_STEPS_MAX):
                errs.append(f"{iid}.method_steps: need {METHOD_STEPS_MIN}-{METHOD_STEPS_MAX} one-line steps")
            else:
                for j, s in enumerate(steps):
                    if word_count(s) > DETAIL_CAPS["idea.method_steps[]"]:
                        errs.append(f"{iid}.method_steps[{j}]: {word_count(s)} words, "
                                    f"cap {DETAIL_CAPS['idea.method_steps[]']}")
        rep = repeated_shingles([i.get("method", "") for i in ideas])
        if rep:
            s, c = rep[0]
            errs.append(f"a {SHINGLE_WORDS}-word passage is repeated in {c} methods ({s[:80]}...): shared "
                        "paragraphs are rejected; each idea's method must be its own experiment, "
                        "without copied boilerplate")
    elif stage_id == "idea_judge":
        for s in data.get("scored") or []:
            d = s.get("distinctness")
            if not isinstance(d, str) or not d.strip():
                errs.append(f"{s.get('idea_id')}.distinctness: missing (<= {DETAIL_CAPS['judge.distinctness']} "
                            "words on what makes this experiment different from its nearest sibling)")
            elif word_count(d) > DETAIL_CAPS["judge.distinctness"]:
                errs.append(f"{s.get('idea_id')}.distinctness: {word_count(d)} words, cap "
                            f"{DETAIL_CAPS['judge.distinctness']}")
    return errs
