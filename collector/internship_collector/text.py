"""Small, dependency-free helpers for employer job descriptions."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")


class _DescriptionContainerParser(HTMLParser):
    """Extract recognizable job-description containers from an HTML page."""

    _MARKER = re.compile(
        r"(?:job(?:[-_ ]?)(?:description|details?)|job__description|jobdescription|"
        r"posting(?:[-_ ]?)(?:description|details?)|description[-_ ]?(?:body|content|text))",
        re.IGNORECASE,
    )
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_depth = 0
        self._ignored_depth = 0
        self._parts: list[str] = []
        self.candidates: list[str] = []

    @classmethod
    def _is_container(cls, attrs: list[tuple[str, str | None]]) -> bool:
        values = " ".join(str(value or "") for key, value in attrs if key.lower() in {"id", "class", "aria-label", "data-testid", "data-test"})
        return bool(cls._MARKER.search(values))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._capture_depth == 0 and tag not in {"script", "style", "template"} and self._is_container(attrs):
            self._capture_depth = 1
            self._parts = []
            return
        if self._capture_depth:
            if tag in self._VOID_TAGS:
                if self._ignored_depth == 0 and tag == "br":
                    self._parts.append("\n")
                return
            self._capture_depth += 1
            if tag in {"script", "style", "template", "form"}:
                self._ignored_depth += 1
            if self._ignored_depth == 0 and tag in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
                self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capture_depth and self._ignored_depth == 0 and tag.lower() in {"br", "p", "div", "li"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._capture_depth:
            return
        if tag in self._VOID_TAGS:
            return
        if tag in {"script", "style", "template", "form"} and self._ignored_depth:
            self._ignored_depth -= 1
        self._capture_depth -= 1
        if self._capture_depth == 0:
            candidate = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._parts))
            candidate = re.sub(r"\n{3,}", "\n\n", candidate).strip()
            if len(candidate.split()) >= 8:
                self.candidates.append(candidate)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_depth and self._ignored_depth == 0:
            self._parts.append(data)


def html_to_text(value: str) -> str:
    """Turn HTML or HTML-escaped HTML into readable plain text."""

    source = value or ""
    # Greenhouse's public API currently returns HTML escaped once. Decode twice
    # so this also handles descriptions copied from an HTML-escaped fixture.
    for _ in range(2):
        decoded = html.unescape(source)
        if decoded == source:
            break
        source = decoded
    parser = _TextParser()
    try:
        parser.feed(source)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", source)
    text = html.unescape(text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_job_description(value: str) -> str:
    """Extract only a marked job-description container from an HTML page.

    The function deliberately returns an empty string for pages whose body is
    only navigation, an application form, or scripts. Callers should then
    record an enrichment error instead of treating the whole page as a JD.
    """

    parser = _DescriptionContainerParser()
    try:
        parser.feed(value or "")
        parser.close()
    except Exception:
        return ""
    if not parser.candidates:
        return ""
    return max(parser.candidates, key=lambda candidate: len(candidate.split()))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if part.strip()]


def _jd_excerpt(value: str) -> str:
    """Select at most 20 words from a role-relevant section."""

    lines = [line.strip() for line in html_to_text(value).splitlines() if line.strip()]
    primary: list[str] = []
    secondary: list[str] = []
    heading_names: list[str] = []
    current_group: list[str] | None = None
    heading_re = re.compile(r"(?:responsibil|what you|the role|about the role|overview|dut(?:y|ies)|impact|qualification|requirement|who you|skills)", re.IGNORECASE)
    for line in lines:
        if len(line) <= 100 and heading_re.search(line):
            heading_names.append(line.rstrip(":"))
            lower = line.casefold()
            current_group = primary if any(marker in lower for marker in ("responsibil", "what you", "the role", "about the role", "overview", "dut", "impact")) else secondary
            continue
        if current_group is not None:
            current_group.append(line)
    candidates = primary or secondary
    if not candidates:
        candidates = _sentences(" ".join(lines))
    boilerplate = re.compile(r"^(?:apply early|about us|about the company|we(?:'|’)re looking|we are looking|equal opportunity|we are committed|our company|the company)\b", re.IGNORECASE)
    for candidate in candidates:
        for sentence in _sentences(candidate):
            if boilerplate.search(sentence):
                continue
            words = sentence.split()
            if sentence.rstrip().endswith(":") and len(words) <= 10:
                continue
            if len(words) >= 5:
                return " ".join(words[:20]).rstrip(" ,;:") + ("…" if len(words) > 20 else "")
    return ""


def summarize_jd(value: str, *, max_chars: int = 640) -> str:
    """Return a short structured summary without copying a full description."""

    text = html_to_text(value)
    if not text:
        return ""
    skill_labels = extract_skills(value)
    pieces: list[str] = []
    excerpt = _jd_excerpt(value)
    if excerpt:
        pieces.append("JD excerpt: " + excerpt)
    if skill_labels:
        pieces.append("Skills named in the posting: " + ", ".join(skill_labels[:16]) + ".")
    if not pieces:
        return ""
    result = " ".join(pieces)
    return result[: max_chars - 1].rstrip() + "…" if len(result) > max_chars else result


_SKILL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("C++", r"(?<!\w)c\+\+(?!\w)"),
    ("C#", r"(?<!\w)c#(?!\w)"),
    (".NET", r"\.net\b"),
    ("JavaScript", r"\b(?:javascript|js)\b"),
    ("TypeScript", r"\btypescript\b"),
    ("Python", r"\bpython\b"),
    ("Java", r"\bjava\b"),
    ("Kotlin", r"\bkotlin\b"),
    ("Swift", r"\bswift\b"),
    ("Go", r"\b(?:golang|go\s+(?:language|programming|development))\b"),
    ("Rust", r"\brust\b"),
    ("Ruby", r"\bruby\b"),
    ("PHP", r"\bphp\b"),
    ("MATLAB", r"\bmatlab\b"),
    ("Bash", r"\bbash\b"),
    ("C", r"(?<![+\w])C(?![+#\w])"),
    ("SQL", r"\bsql\b"),
    ("React", r"\breact(?:\.js)?\b"),
    ("Node.js", r"\bnode(?:\.js|js)\b"),
    ("GraphQL", r"\bgraphql\b"),
    ("Git", r"\bgit(?:hub|lab)?\b"),
    ("Linux", r"\blinux\b"),
    ("AWS", r"\baws\b|amazon web services"),
    ("GCP", r"\bgcp\b|google cloud"),
    ("Azure", r"\bazure\b"),
    ("Docker", r"\bdocker\b"),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("Terraform", r"\bterraform\b"),
    ("Airflow", r"\bairflow\b"),
    ("MLflow", r"\bmlflow\b"),
    ("Kubeflow", r"\bkubeflow\b"),
    ("Hugging Face", r"\bhugging face\b"),
    ("LangChain", r"\blangchain\b"),
    ("RAG", r"\brag\b|retrieval[- ]augmented generation"),
    ("FastAPI", r"\bfastapi\b"),
    ("vLLM", r"\bvllm\b"),
    ("Spark", r"\bspark\b"),
    ("Databricks", r"\bdatabricks\b"),
    ("Snowflake", r"\bsnowflake\b"),
    ("PostgreSQL", r"\bpostgres(?:ql)?\b"),
    ("MySQL", r"\bmysql\b"),
    ("MongoDB", r"\bmongodb\b"),
    ("Redis", r"\bredis\b"),
    ("TensorFlow", r"\btensorflow\b"),
    ("PyTorch", r"\bpytorch\b"),
    ("scikit-learn", r"\bscikit[- ]learn\b"),
    ("pandas", r"\bpandas\b"),
    ("NumPy", r"\bnumpy\b"),
    ("OpenCV", r"\bopencv\b"),
    ("CUDA", r"\bcuda\b"),
    ("FPGA", r"\bfpga\b"),
    ("Verilog", r"\bverilog\b"),
    ("Machine learning", r"\bmachine learning\b|\bml\b"),
    ("Deep learning", r"\bdeep learning\b"),
    ("Computer vision", r"\bcomputer vision\b"),
    ("Natural language processing", r"\bnatural language processing\b|\bnlp\b"),
    ("LLMs", r"\bllm(?:s)?\b|large language models?"),
)


def extract_skills(value: str) -> list[str]:
    """Extract a controlled vocabulary of explicitly mentioned skills."""

    text = html_to_text(value)
    found: list[str] = []
    for label, pattern in _SKILL_PATTERNS:
        flags = 0 if label in {"C", "RAG"} else re.IGNORECASE
        if re.search(pattern, text, flags):
            if label == "C" and not re.search(r"(?<![\w+#])C\s+(?:programming|language|code|development)\b", text):
                continue
            found.append(label)
    return found


DOMAIN_VALUES = (
    "Computer Vision",
    "MLOps / AI Infrastructure",
    "Machine Learning / AI",
    "Data",
    "Software Engineering",
    "Cybersecurity",
    "Hardware / Robotics",
    "Product / Design",
    "Business / Other",
)


def classify_domain(role: str, jd: str = "", skills: list[str] | tuple[str, ...] = ()) -> str:
    """Assign one practical filter category from the role and collected details."""

    title = " ".join((role or "").casefold().split())
    detail = " ".join((jd or "").casefold().split())
    skill_text = " ".join(str(skill).casefold() for skill in skills)
    text = f"{title} {detail} {skill_text}"

    if re.search(r"\bcomputer vision\b|\bmachine vision\b|\bimage processing\b|\bperception\b|\bopencv\b", text):
        return "Computer Vision"
    if re.search(r"\bmlops\b|\bai infrastructure\b|\bml infrastructure\b|\bmachine learning infrastructure\b|\bmodel serving\b|\bml platform\b", text):
        return "MLOps / AI Infrastructure"
    if re.search(r"\bmachine learning\b|\bartificial intelligence\b|\bapplied ai\b|\bgenerative ai\b|\bdeep learning\b|\bnlp\b|\bllm", text):
        return "Machine Learning / AI"
    if re.search(r"\bdata scientist\b|\bdata science\b|\bdata engineer\b|\bdata engineering\b|\banalytics?\b|\bbusiness intelligence\b|\bdatabase\b", text):
        return "Data"
    if re.search(r"\bcyber(?:security)?\b|\binformation security\b|\bsecurity engineer\b|\bthreat\b|\bpenetration test", text):
        return "Cybersecurity"
    if re.search(r"\brobotics?\b|\bembedded\b|\bfirmware\b|\bhardware\b|\belectrical\b|\bmechanical\b|\bfpga\b|\bavionics\b", text):
        return "Hardware / Robotics"
    if re.search(r"\bsoftware\b|\bdeveloper\b|\bfull[ -]?stack\b|\bfront[ -]?end\b|\bback[ -]?end\b|\bmobile\b|\bweb\b|\bcloud\b|\bdevops\b|\bsre\b", text):
        return "Software Engineering"
    if re.search(r"\bproduct\b|\bdesign\b|\bux\b|\bui\b", text):
        return "Product / Design"
    return "Business / Other"


def _evidence_sentence(text: str, match: re.Match[str]) -> str:
    start = text.rfind(".", 0, match.start()) + 1
    end_match = re.search(r"[.!?](?:\s|$)", text[match.end() :])
    end = match.end() + (end_match.end() if end_match else 220)
    sentence = " ".join(text[start:end].split())
    words = sentence.split()
    return " ".join(words[:25]).rstrip(" ,;:") + ("…" if len(words) > 25 else "")


def detect_visa_sponsorship(value: str) -> tuple[str, str]:
    """Classify only explicit sponsorship language.

    Export-control, citizenship, and work-authorization language does not imply
    a sponsorship denial, so it leaves the value at ``not stated``.
    """

    text = html_to_text(value)
    positive = re.compile(
        r"(?:we|our company|the company|employer)?\s*(?:will|can|do|does)\s+(?:sponsor|provide)\b[^.]{0,100}\b(?:visa|visas|sponsorship)\b"
        r"|\bvisa sponsorship\s+(?:is\s+)?(?:available|provided|offered)\b"
        r"|\b(?:we|the company|employer)\s+sponsor(?:s)?\s+(?:us|u\.s\.|international)?\s*visas?\b",
        re.IGNORECASE,
    )
    negative = re.compile(
        r"\b(?:we|the company|employer)\s+(?:do|does|will|can)\s+not\s+sponsor\b[^.]{0,100}\b(?:visa|visas|sponsorship)?\b"
        r"|\b(?:no|without)\s+(?:visa\s+)?sponsorship\b"
        r"|\bvisa sponsorship\s+(?:is\s+)?(?:not available|unavailable|not offered|not provided)\b"
        r"|\bunable to sponsor\b",
        re.IGNORECASE,
    )
    positive_match = positive.search(text)
    negative_match = negative.search(text)
    if positive_match and negative_match:
        return "not stated", "Posting has conflicting sponsorship statements."
    if positive_match:
        return "provided", "Employer states visa sponsorship is offered."
    if negative_match:
        return "not provided", "Employer states visa sponsorship is unavailable."
    return "not stated", ""
