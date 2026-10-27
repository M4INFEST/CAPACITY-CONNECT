import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 500_000
MAX_PDF_PAGES = 100
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
_WORD_CHAR = r"A-Za-z0-9_"
_AMBIGUOUS_SKILLS = {"c"}
_PROGRAMMING_CONTEXT = re.compile(
    r"\b(program(?:ming)?|language|developer|software|code|compiler|"
    r"application|engineer|backend|frontend)\b",
    re.IGNORECASE,
)
_NEGATIVE_CONTEXT = re.compile(
    r"\b(?:no|not|without)\s+(?:prior\s+|professional\s+)?"
    r"(?:experience|work|knowledge|use|using)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SkillAlias:
    competency_id: str
    skill_name: str
    alias: str
    must_not_match: tuple[str, ...]


@dataclass(frozen=True)
class SkillMatch:
    competency_id: str
    skill_name: str
    alias: str
    confidence_score: float
    context: str

    @property
    def requires_manual_review(self) -> bool:
        return self.confidence_score < 0.9


def extract_document_text(filename: str, content: bytes) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf":
        return _extract_pdf_text(content)
    if extension == "docx":
        return _extract_docx_text(content)
    raise ValueError("Upload a PDF or DOCX resume")


def _extract_pdf_text(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDFs may contain at most {MAX_PDF_PAGES} pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as error:
        raise ValueError("The PDF could not be read") from error
    return _validate_extracted_text(text)


def _extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            try:
                document_info = archive.getinfo("word/document.xml")
            except KeyError as error:
                raise ValueError("The DOCX document body is missing") from error
            if document_info.file_size > MAX_DOCX_XML_BYTES:
                raise ValueError("The DOCX document contains too much uncompressed text")
            document = ElementTree.fromstring(archive.read(document_info))
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError) as error:
        raise ValueError("The uploaded file is not a valid DOCX") from error

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in document.iter(f"{namespace}p"):
        words = [
            node.text or ""
            for node in paragraph.iter()
            if node.tag == f"{namespace}t"
        ]
        if words:
            paragraphs.append("".join(words))
    return _validate_extracted_text("\n".join(paragraphs))


def _validate_extracted_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise ValueError(
            "No readable text was found. Scanned or image-only resumes are not supported yet."
        )
    if len(normalized) > MAX_EXTRACTED_CHARS:
        raise ValueError("The resume contains too much text to process")
    return normalized


def match_skills(text: str, aliases: list[SkillAlias]) -> list[SkillMatch]:
    best_by_competency: dict[str, SkillMatch] = {}
    spans: list[tuple[int, int, SkillAlias]] = []
    for alias in aliases:
        pattern = _alias_pattern(alias.alias)
        for match in pattern.finditer(text):
            following = text[match.end() :].lower()
            if any(
                following.startswith(exclusion.lower())
                for exclusion in alias.must_not_match
            ):
                continue
            spans.append((match.start(), match.end(), alias))

    non_overlapping: list[tuple[int, int, SkillAlias]] = []
    last_end = 0
    for span in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]))):
        if span[0] < last_end:
            continue
        non_overlapping.append(span)
        last_end = span[1]

    # Technical context markers inspired by skill-extractor and resume-ner
    action_verb_pattern = re.compile(
        r"\b(built|designed|implemented|architected|developed|deployed|engineered|"
        r"optimized|configured|maintained|authored|refactored|tested|debugged|managed|"
        r"integrated|analyzed|automated|created|led|produced|specialized)\b",
        re.IGNORECASE,
    )
    section_header_pattern = re.compile(
        r"\b(skills|technical\s+skills|technologies|proficiencies|competencies|tools|"
        r"languages|frameworks|experience|projects|education)\b",
        re.IGNORECASE,
    )

    for start, end, alias in non_overlapping:
        context = _word_context(text, start, end)
        
        # Base confidence
        score = 0.94
        
        # Strong indicators: presence of technical action verbs or skill sections
        if action_verb_pattern.search(context):
            score += 0.04
        if section_header_pattern.search(context):
            score += 0.02
            
        # Negative indicators
        if _NEGATIVE_CONTEXT.search(context):
            score = min(score, 0.72)

            
        # Ambiguous single-letter/symbol skills (e.g. 'c')
        if alias.skill_name.casefold() in _AMBIGUOUS_SKILLS:
            if _PROGRAMMING_CONTEXT.search(context) and not _NEGATIVE_CONTEXT.search(context):
                score = max(0.91, score)
            elif _NEGATIVE_CONTEXT.search(context):
                score = min(score, 0.72)
            else:
                score = min(0.68, score)


        confidence = round(max(0.1, min(0.99, score)), 2)

        candidate = SkillMatch(
            competency_id=alias.competency_id,
            skill_name=alias.skill_name,
            alias=alias.alias,
            confidence_score=confidence,
            context=context,
        )
        current = best_by_competency.get(alias.competency_id)
        if current is None or candidate.confidence_score > current.confidence_score:
            best_by_competency[alias.competency_id] = candidate
    return sorted(best_by_competency.values(), key=lambda item: item.skill_name.casefold())


def _word_context(text: str, start: int, end: int) -> str:
    words = text.split()
    word_index = len(text[:start].split())
    match_end_word_index = len(text[:end].split())
    lower = max(0, word_index - 20)
    upper = min(len(words), max(match_end_word_index, word_index + 1) + 21)
    return " ".join(words[lower:upper])


def _alias_pattern(alias: str) -> re.Pattern[str]:
    parts = re.split(r"(\s+)", alias.strip())
    literal = "".join(r"\s+" if part.isspace() else re.escape(part) for part in parts)
    return re.compile(
        rf"(?<![{_WORD_CHAR}]){literal}(?![{_WORD_CHAR}])",
        re.IGNORECASE,
    )
