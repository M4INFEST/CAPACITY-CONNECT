import unittest
import zipfile
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.services.skill_extraction import (
    SkillAlias,
    _extract_docx_text,
    _extract_pdf_text,
    match_skills,
)


ALIASES = [
    SkillAlias("java-id", "Java", "Java", ()),
    SkillAlias("javascript-id", "JavaScript", "JavaScript", ()),
    SkillAlias("c-id", "C", "C", ("++", "#", " sharp", " plus plus")),
    SkillAlias("cpp-id", "C++", "C++", ()),
    SkillAlias("csharp-id", "C#", "C#", ()),
    SkillAlias("dotnet-id", "Microsoft .NET", ".NET", ()),
    SkillAlias("node-id", "Node.js", "Node.js", ()),
]


def make_docx(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        + text
        + "</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def make_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class TaxonomyMatchingTests(unittest.TestCase):
    def test_distinguishes_java_javascript_and_c_family_symbols(self) -> None:
        matches = match_skills(
            "Built services in JavaScript and Java, then wrote C++, C#, and C.",
            ALIASES,
        )
        found = {match.skill_name for match in matches}

        self.assertEqual(found, {"Java", "JavaScript", "C", "C++", "C#"})
        confidence = {match.skill_name: match.confidence_score for match in matches}
        self.assertGreaterEqual(confidence["Java"], 0.9)
        self.assertLess(confidence["C"], 0.9)
        self.assertTrue(next(match for match in matches if match.skill_name == "C").requires_manual_review)

    def test_symbol_and_dot_boundaries(self) -> None:
        found = {
            match.skill_name
            for match in match_skills("Used .NET and Node.js in production.", ALIASES)
        }
        self.assertEqual(found, {"Microsoft .NET", "Node.js"})

    def test_java_does_not_match_inside_javascript(self) -> None:
        found = {
            match.skill_name
            for match in match_skills("JavaScript only.", ALIASES)
        }
        self.assertEqual(found, {"JavaScript"})

    def test_negative_context_requires_review(self) -> None:
        match = match_skills("I have no experience with C.", ALIASES)[0]
        self.assertEqual(match.confidence_score, 0.72)
        self.assertTrue(match.requires_manual_review)


class DocumentParsingTests(unittest.TestCase):
    def test_extracts_text_from_docx(self) -> None:
        self.assertEqual(_extract_docx_text(make_docx("Python and PostgreSQL")), "Python and PostgreSQL")

    def test_rejects_invalid_pdf_signature(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid PDF"):
            _extract_pdf_text(b"not a pdf")

    def test_extracts_text_from_pdf(self) -> None:
        self.assertEqual(_extract_pdf_text(make_pdf("Python skills")), "Python skills")


if __name__ == "__main__":
    unittest.main()
