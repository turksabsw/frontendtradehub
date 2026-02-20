# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Text Field Handlers Module.

This module provides handlers for text-based Frappe field types that generate
multi-line or formatted text content:

- SmallTextHandler: For Small Text fields (up to 255 chars)
- TextHandler: For Text fields (unlimited plain text)
- LongTextHandler: For Long Text fields (very long content)
- TextEditorHandler: For Text Editor fields (HTML content)
- CodeFieldHandler: For Code fields (code snippets)
- MarkdownHandler: For Markdown Editor fields (markdown content)

These handlers complement the DataHandler which handles single-line Data fields.
Each handler generates appropriate content based on the field's semantic pattern
(description, notes, comments, etc.) and respects max_length constraints.

Usage:
    from mock_data_engine.handlers.text_handlers import (
        TextHandler,
        TextEditorHandler,
        CodeFieldHandler,
    )

    # Using TextHandler for text content
    handler = TextHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)

    # Using CodeFieldHandler for code snippets
    code_handler = CodeFieldHandler(locale='en_US')
    code = code_handler.generate(context)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.core.config_resolver import ResolvedConfig


class SmallTextHandler(BaseFieldHandler):
    """
    Handler for Small Text field generation.

    Small Text fields in Frappe are limited to 255 characters and are typically
    used for short descriptions, notes, or comments that need more space than
    a single-line Data field but don't require multi-paragraph content.

    Supported patterns:
        - FieldPattern.DESCRIPTION (short description)
        - FieldPattern.NOTES (brief notes)
        - FieldPattern.COMMENT (short comments)
        - FieldPattern.REMARKS (brief remarks)
        - FieldPattern.GENERIC (generic short text)

    Example:
        >>> handler = SmallTextHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Bu ürün yüksek kaliteli malzemelerden üretilmiştir ve dayanıklıdır.'
    """

    # Maximum length for Small Text (Frappe default)
    MAX_LENGTH = 255

    def generate(self, context: GenerationContext) -> str:
        """
        Generate small text content.

        Args:
            context: The generation context

        Returns:
            A short text string (up to 255 chars)
        """
        max_length = min(context.max_length or self.MAX_LENGTH, self.MAX_LENGTH)

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

        # Get detected pattern for contextual generation
        pattern = context.detected_pattern or self.detect_pattern(context)

        # Generate based on pattern
        if pattern == FieldPattern.DESCRIPTION:
            return self._generate_description(max_length)
        elif pattern == FieldPattern.NOTES:
            return self._generate_notes(max_length)
        elif pattern == FieldPattern.COMMENT:
            return self._generate_comment(max_length)
        elif pattern == FieldPattern.REMARKS:
            return self._generate_remarks(max_length)
        else:
            return self._generate_generic(max_length)

    def _generate_description(self, max_length: int) -> str:
        """Generate a short description."""
        # Generate 1-2 sentences
        sentences = self.faker.sentences(nb=2)
        text = " ".join(sentences)
        return text[:max_length]

    def _generate_notes(self, max_length: int) -> str:
        """Generate brief notes."""
        # Notes are typically bullet-point style or brief observations
        note_prefixes = ["Note:", "Important:", "Remember:", "See also:", "FYI:"]
        prefix = self.faker.random_element(note_prefixes)
        content = self.faker.sentence(nb_words=10)
        text = f"{prefix} {content}"
        return text[:max_length]

    def _generate_comment(self, max_length: int) -> str:
        """Generate a short comment."""
        return self.faker.sentence(nb_words=8)[:max_length]

    def _generate_remarks(self, max_length: int) -> str:
        """Generate brief remarks."""
        return self.faker.sentence(nb_words=12)[:max_length]

    def _generate_generic(self, max_length: int) -> str:
        """Generate generic short text."""
        # Adjust sentence count based on max length
        if max_length <= 50:
            return self.faker.sentence(nb_words=5)[:max_length]
        elif max_length <= 100:
            return self.faker.sentence(nb_words=10)[:max_length]
        else:
            sentences = self.faker.sentences(nb=2)
            return " ".join(sentences)[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate small text format."""
        if not isinstance(value, str):
            return False
        max_length = min(context.max_length or self.MAX_LENGTH, self.MAX_LENGTH)
        return len(value) <= max_length

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DESCRIPTION,
            FieldPattern.NOTES,
            FieldPattern.COMMENT,
            FieldPattern.REMARKS,
            FieldPattern.GENERIC,
        }


class TextHandler(BaseFieldHandler):
    """
    Handler for Text field generation.

    Text fields in Frappe are unlimited in length but typically used for
    medium-length content like descriptions, summaries, or multi-line notes.

    This handler generates plain text content with appropriate paragraph
    structure based on the detected semantic pattern.

    Supported patterns:
        - FieldPattern.DESCRIPTION
        - FieldPattern.NOTES
        - FieldPattern.COMMENT
        - FieldPattern.REMARKS
        - FieldPattern.GENERIC

    Example:
        >>> handler = TextHandler(locale='en_US')
        >>> handler.generate(context)
        'Lorem ipsum dolor sit amet, consectetur adipiscing elit...'
    """

    # Default length for Text fields when not specified
    DEFAULT_LENGTH = 500

    def generate(self, context: GenerationContext) -> str:
        """
        Generate text content.

        Args:
            context: The generation context

        Returns:
            A multi-line text string
        """
        max_length = context.max_length or self.DEFAULT_LENGTH

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

            # Check for paragraph count override
            paragraph_count = context.get_override_value("paragraph_count")
            if paragraph_count:
                return self._generate_paragraphs(paragraph_count, max_length)

        # Get detected pattern for contextual generation
        pattern = context.detected_pattern or self.detect_pattern(context)

        # Generate based on pattern
        if pattern == FieldPattern.DESCRIPTION:
            return self._generate_description(max_length)
        elif pattern == FieldPattern.NOTES:
            return self._generate_notes(max_length)
        elif pattern == FieldPattern.COMMENT:
            return self._generate_comment(max_length)
        elif pattern == FieldPattern.REMARKS:
            return self._generate_remarks(max_length)
        else:
            return self._generate_generic(max_length)

    def _generate_paragraphs(self, count: int, max_length: int) -> str:
        """Generate specified number of paragraphs."""
        paragraphs = self.faker.paragraphs(nb=count)
        text = "\n\n".join(paragraphs)
        return text[:max_length]

    def _generate_description(self, max_length: int) -> str:
        """Generate a description."""
        # Determine paragraph count based on max length
        if max_length <= 200:
            text = self.faker.paragraph(nb_sentences=3)
        elif max_length <= 500:
            paragraphs = self.faker.paragraphs(nb=2)
            text = "\n\n".join(paragraphs)
        else:
            paragraphs = self.faker.paragraphs(nb=3)
            text = "\n\n".join(paragraphs)
        return text[:max_length]

    def _generate_notes(self, max_length: int) -> str:
        """Generate notes content."""
        # Notes typically have bullet-point style
        note_count = min(5, max_length // 100 + 1)
        notes = []
        for _ in range(note_count):
            note = f"- {self.faker.sentence(nb_words=10)}"
            notes.append(note)
        text = "\n".join(notes)
        return text[:max_length]

    def _generate_comment(self, max_length: int) -> str:
        """Generate comment content."""
        return self.faker.paragraph(nb_sentences=4)[:max_length]

    def _generate_remarks(self, max_length: int) -> str:
        """Generate remarks content."""
        return self.faker.paragraph(nb_sentences=3)[:max_length]

    def _generate_generic(self, max_length: int) -> str:
        """Generate generic text content."""
        # Use faker's text method which respects max length
        if max_length <= 200:
            return self.faker.text(max_nb_chars=max_length)
        else:
            paragraphs = self.faker.paragraphs(nb=max_length // 200 + 1)
            text = "\n\n".join(paragraphs)
            return text[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate text format."""
        if not isinstance(value, str):
            return False
        if context.max_length and len(value) > context.max_length:
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DESCRIPTION,
            FieldPattern.NOTES,
            FieldPattern.COMMENT,
            FieldPattern.REMARKS,
            FieldPattern.GENERIC,
        }


class LongTextHandler(BaseFieldHandler):
    """
    Handler for Long Text field generation.

    Long Text fields in Frappe are used for extensive content such as
    detailed descriptions, full articles, or comprehensive documentation.

    This handler generates substantial multi-paragraph content.

    Supported patterns:
        - FieldPattern.DESCRIPTION
        - FieldPattern.NOTES
        - FieldPattern.GENERIC

    Example:
        >>> handler = LongTextHandler(locale='en_US')
        >>> handler.generate(context)
        'Lorem ipsum dolor sit amet...' (multiple paragraphs)
    """

    # Default length for Long Text fields
    DEFAULT_LENGTH = 2000

    def generate(self, context: GenerationContext) -> str:
        """
        Generate long text content.

        Args:
            context: The generation context

        Returns:
            A multi-paragraph text string
        """
        max_length = context.max_length or self.DEFAULT_LENGTH

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

            # Check for paragraph count override
            paragraph_count = context.get_override_value("paragraph_count")
            if paragraph_count:
                return self._generate_paragraphs(paragraph_count, max_length)

        # Generate substantial content
        return self._generate_long_content(max_length)

    def _generate_paragraphs(self, count: int, max_length: int) -> str:
        """Generate specified number of paragraphs."""
        paragraphs = self.faker.paragraphs(nb=count)
        text = "\n\n".join(paragraphs)
        return text[:max_length]

    def _generate_long_content(self, max_length: int) -> str:
        """Generate long text content."""
        # Calculate approximate paragraph count
        # Average paragraph is about 300-400 characters
        paragraph_count = max(3, max_length // 350)

        paragraphs = self.faker.paragraphs(nb=paragraph_count)
        text = "\n\n".join(paragraphs)
        return text[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate long text format."""
        if not isinstance(value, str):
            return False
        if context.max_length and len(value) > context.max_length:
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DESCRIPTION,
            FieldPattern.NOTES,
            FieldPattern.GENERIC,
        }


class TextEditorHandler(BaseFieldHandler):
    """
    Handler for Text Editor field generation.

    Text Editor fields in Frappe use a WYSIWYG editor and store HTML content.
    This handler generates properly formatted HTML content with common
    elements like paragraphs, headings, lists, and basic formatting.

    Supported patterns:
        - FieldPattern.DESCRIPTION
        - FieldPattern.NOTES
        - FieldPattern.GENERIC

    Example:
        >>> handler = TextEditorHandler(locale='en_US')
        >>> handler.generate(context)
        '<h2>Title</h2><p>Content paragraph...</p>'
    """

    # Default length for Text Editor fields
    DEFAULT_LENGTH = 1000

    def generate(self, context: GenerationContext) -> str:
        """
        Generate HTML content for text editor.

        Args:
            context: The generation context

        Returns:
            An HTML formatted string
        """
        max_length = context.max_length or self.DEFAULT_LENGTH

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

            # Check for HTML template override
            html_template = context.get_override_value("html_template")
            if html_template:
                return html_template[:max_length]

        # Get detected pattern for contextual generation
        pattern = context.detected_pattern or self.detect_pattern(context)

        # Generate HTML based on pattern
        if pattern == FieldPattern.DESCRIPTION:
            return self._generate_html_description(max_length)
        elif pattern == FieldPattern.NOTES:
            return self._generate_html_notes(max_length)
        else:
            return self._generate_html_content(max_length)

    def _generate_html_description(self, max_length: int) -> str:
        """Generate HTML description content."""
        # Generate a title and description paragraphs
        title = self.faker.sentence(nb_words=5).rstrip(".")
        paragraphs = self.faker.paragraphs(nb=2)

        html_parts = [
            f"<h3>{title}</h3>",
        ]

        for para in paragraphs:
            html_parts.append(f"<p>{para}</p>")

        html = "\n".join(html_parts)
        return html[:max_length]

    def _generate_html_notes(self, max_length: int) -> str:
        """Generate HTML notes with bullet list."""
        # Generate a list of notes
        note_count = min(5, max_length // 150 + 1)
        items = [self.faker.sentence(nb_words=8) for _ in range(note_count)]

        html_parts = [
            "<h4>Notes</h4>",
            "<ul>",
        ]

        for item in items:
            html_parts.append(f"  <li>{item}</li>")

        html_parts.append("</ul>")

        html = "\n".join(html_parts)
        return html[:max_length]

    def _generate_html_content(self, max_length: int) -> str:
        """Generate generic HTML content."""
        html_parts = []

        # Add a heading
        heading = self.faker.sentence(nb_words=4).rstrip(".")
        html_parts.append(f"<h3>{heading}</h3>")

        # Add paragraphs
        paragraph_count = max(1, max_length // 300)
        for _ in range(paragraph_count):
            para = self.faker.paragraph(nb_sentences=3)
            # Add some basic formatting randomly
            if self.faker.boolean(chance_of_getting_true=30):
                # Add bold text
                words = para.split()
                if len(words) > 3:
                    bold_word = self.faker.random_element(words[:len(words)//2])
                    para = para.replace(bold_word, f"<strong>{bold_word}</strong>", 1)
            html_parts.append(f"<p>{para}</p>")

        # Optionally add a list
        if max_length > 500 and self.faker.boolean(chance_of_getting_true=50):
            html_parts.append("<ul>")
            list_items = min(3, (max_length - len("\n".join(html_parts))) // 100)
            for _ in range(list_items):
                item = self.faker.sentence(nb_words=6)
                html_parts.append(f"  <li>{item}</li>")
            html_parts.append("</ul>")

        html = "\n".join(html_parts)
        return html[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate HTML content."""
        if not isinstance(value, str):
            return False
        if context.max_length and len(value) > context.max_length:
            return False
        # Basic HTML validation - check for common tags
        # Note: Frappe's Text Editor accepts various HTML
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DESCRIPTION,
            FieldPattern.NOTES,
            FieldPattern.GENERIC,
        }


class CodeFieldHandler(BaseFieldHandler):
    """
    Handler for Code field generation.

    Code fields in Frappe are used to store code snippets, JSON, XML,
    or other structured text. This handler generates realistic code
    samples in various programming languages.

    Note: This is different from CodeHandler in data_handlers which
    generates alphanumeric codes/identifiers like SKUs.

    Supported languages:
        - Python
        - JavaScript
        - JSON
        - SQL
        - HTML
        - CSS

    Example:
        >>> handler = CodeFieldHandler(locale='en_US')
        >>> handler.generate(context)
        'def hello_world():\\n    print("Hello, World!")\\n    return True'
    """

    # Default length for Code fields
    DEFAULT_LENGTH = 500

    # Code templates for different languages
    CODE_TEMPLATES: Dict[str, List[str]] = {
        "python": [
            '''def {func_name}({params}):
    """{docstring}"""
    {body}
    return {return_val}''',
            '''class {class_name}:
    """{docstring}"""

    def __init__(self, {params}):
        {init_body}

    def {method_name}(self):
        {method_body}''',
            '''# {comment}
{var_name} = {value}
for item in {var_name}:
    print(item)''',
        ],
        "javascript": [
            '''function {func_name}({params}) {{
    // {comment}
    {body}
    return {return_val};
}}''',
            '''const {var_name} = ({params}) => {{
    {body}
    return {return_val};
}};''',
            '''class {class_name} {{
    constructor({params}) {{
        {init_body}
    }}

    {method_name}() {{
        {method_body}
    }}
}}''',
        ],
        "json": [
            '''{{"name": "{name}", "value": {value}, "enabled": {enabled}}}''',
            '''{{"items": [{{"id": {id1}, "name": "{name1}"}}, {{"id": {id2}, "name": "{name2}"}}]}}''',
            '''{{"config": {{"setting1": "{setting1}", "setting2": {setting2}, "options": [{option_list}]}}}}''',
        ],
        "sql": [
            '''SELECT {columns}
FROM {table}
WHERE {condition}
ORDER BY {order_col};''',
            '''INSERT INTO {table} ({columns})
VALUES ({values});''',
            '''UPDATE {table}
SET {set_clause}
WHERE {condition};''',
        ],
        "html": [
            '''<div class="{class_name}">
    <h2>{title}</h2>
    <p>{content}</p>
</div>''',
            '''<ul class="{class_name}">
    <li>{item1}</li>
    <li>{item2}</li>
    <li>{item3}</li>
</ul>''',
        ],
        "css": [
            '''.{class_name} {{
    {property1}: {value1};
    {property2}: {value2};
    {property3}: {value3};
}}''',
            '''#{id_name} {{
    display: {display};
    margin: {margin};
    padding: {padding};
}}''',
        ],
    }

    def generate(self, context: GenerationContext) -> str:
        """
        Generate code content.

        Args:
            context: The generation context

        Returns:
            A code snippet string
        """
        max_length = context.max_length or self.DEFAULT_LENGTH

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

            # Check for language override
            language = context.get_override_value("language")
            if language:
                return self._generate_code_for_language(language, max_length)

        # Detect language from field name or generate default
        language = self._detect_language(context.fieldname)
        return self._generate_code_for_language(language, max_length)

    def _detect_language(self, fieldname: str) -> str:
        """Detect programming language from field name."""
        fieldname_lower = fieldname.lower()

        if any(kw in fieldname_lower for kw in ["python", "py_"]):
            return "python"
        elif any(kw in fieldname_lower for kw in ["javascript", "js_", "_js"]):
            return "javascript"
        elif any(kw in fieldname_lower for kw in ["json", "config", "settings"]):
            return "json"
        elif any(kw in fieldname_lower for kw in ["sql", "query"]):
            return "sql"
        elif any(kw in fieldname_lower for kw in ["html", "template", "markup"]):
            return "html"
        elif any(kw in fieldname_lower for kw in ["css", "style"]):
            return "css"
        else:
            # Default to Python as it's commonly used
            return "python"

    def _generate_code_for_language(self, language: str, max_length: int) -> str:
        """Generate code for a specific language."""
        templates = self.CODE_TEMPLATES.get(language, self.CODE_TEMPLATES["python"])
        template = self.faker.random_element(templates)

        # Generate placeholder values
        code = self._fill_template(template, language)
        return code[:max_length]

    def _fill_template(self, template: str, language: str) -> str:
        """Fill a code template with generated values."""
        # Common variable names
        var_names = ["data", "result", "items", "config", "value", "count", "total"]
        func_names = ["process", "calculate", "validate", "transform", "get", "set", "handle"]
        class_names = ["Handler", "Manager", "Service", "Controller", "Helper"]
        method_names = ["execute", "run", "process", "update", "get_data", "save"]

        # Generate replacements
        replacements = {
            # Names
            "{func_name}": self.faker.random_element(func_names) + "_" + self.faker.word()[:6],
            "{class_name}": self.faker.random_element(class_names),
            "{method_name}": self.faker.random_element(method_names),
            "{var_name}": self.faker.random_element(var_names),

            # Parameters and values
            "{params}": ", ".join(self.faker.words(nb=2)),
            "{return_val}": self.faker.random_element(["True", "False", "result", "data", "None"]),
            "{value}": str(self.faker.random_int(min=1, max=100)),

            # Documentation
            "{docstring}": self.faker.sentence(nb_words=6).rstrip("."),
            "{comment}": self.faker.sentence(nb_words=5).rstrip("."),

            # Body content
            "{body}": f"result = {self.faker.random_element(var_names)}",
            "{init_body}": f"self.value = {self.faker.random_element(var_names)}",
            "{method_body}": f"return self.value",

            # SQL specific
            "{table}": self.faker.word() + "s",
            "{columns}": ", ".join(self.faker.words(nb=3)),
            "{condition}": f"id = {self.faker.random_int(min=1, max=100)}",
            "{order_col}": "created_at",
            "{values}": ", ".join([f"'{self.faker.word()}'" for _ in range(3)]),
            "{set_clause}": f"status = 'active'",

            # JSON specific
            "{name}": self.faker.word(),
            "{enabled}": self.faker.random_element(["true", "false"]),
            "{id1}": str(self.faker.random_int(min=1, max=100)),
            "{id2}": str(self.faker.random_int(min=101, max=200)),
            "{name1}": self.faker.word(),
            "{name2}": self.faker.word(),
            "{setting1}": self.faker.word(),
            "{setting2}": str(self.faker.random_int(min=1, max=10)),
            "{option_list}": ", ".join([f'"{w}"' for w in self.faker.words(nb=3)]),

            # HTML/CSS specific
            "{title}": self.faker.sentence(nb_words=3).rstrip("."),
            "{content}": self.faker.sentence(nb_words=8),
            "{item1}": self.faker.word().capitalize(),
            "{item2}": self.faker.word().capitalize(),
            "{item3}": self.faker.word().capitalize(),
            "{id_name}": self.faker.word() + "-container",
            "{property1}": self.faker.random_element(["color", "font-size", "background"]),
            "{value1}": self.faker.random_element(["#333", "16px", "#fff"]),
            "{property2}": self.faker.random_element(["margin", "padding", "border"]),
            "{value2}": self.faker.random_element(["10px", "0", "1px solid #ccc"]),
            "{property3}": self.faker.random_element(["display", "position", "width"]),
            "{value3}": self.faker.random_element(["block", "relative", "100%"]),
            "{display}": self.faker.random_element(["flex", "block", "grid"]),
            "{margin}": self.faker.random_element(["0", "10px", "auto"]),
            "{padding}": self.faker.random_element(["10px", "15px", "20px"]),
        }

        code = template
        for key, value in replacements.items():
            code = code.replace(key, value)

        return code

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate code content."""
        if not isinstance(value, str):
            return False
        if context.max_length and len(value) > context.max_length:
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.GENERIC}


class MarkdownHandler(BaseFieldHandler):
    """
    Handler for Markdown Editor field generation.

    Markdown Editor fields in Frappe use markdown syntax for formatting.
    This handler generates properly formatted markdown content with
    headings, lists, emphasis, and other common markdown elements.

    Supported patterns:
        - FieldPattern.DESCRIPTION
        - FieldPattern.NOTES
        - FieldPattern.GENERIC

    Example:
        >>> handler = MarkdownHandler(locale='en_US')
        >>> handler.generate(context)
        '## Title\\n\\nParagraph content...\\n\\n- Item 1\\n- Item 2'
    """

    # Default length for Markdown fields
    DEFAULT_LENGTH = 1000

    def generate(self, context: GenerationContext) -> str:
        """
        Generate markdown content.

        Args:
            context: The generation context

        Returns:
            A markdown formatted string
        """
        max_length = context.max_length or self.DEFAULT_LENGTH

        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:max_length]

        # Get detected pattern for contextual generation
        pattern = context.detected_pattern or self.detect_pattern(context)

        # Generate markdown based on pattern
        if pattern == FieldPattern.DESCRIPTION:
            return self._generate_markdown_description(max_length)
        elif pattern == FieldPattern.NOTES:
            return self._generate_markdown_notes(max_length)
        else:
            return self._generate_markdown_content(max_length)

    def _generate_markdown_description(self, max_length: int) -> str:
        """Generate markdown description content."""
        md_parts = []

        # Add heading
        title = self.faker.sentence(nb_words=4).rstrip(".")
        md_parts.append(f"## {title}")
        md_parts.append("")

        # Add description paragraphs
        paragraph_count = max(1, max_length // 400)
        for _ in range(paragraph_count):
            para = self.faker.paragraph(nb_sentences=3)
            # Add some emphasis randomly
            if self.faker.boolean(chance_of_getting_true=30):
                words = para.split()
                if len(words) > 3:
                    bold_word = self.faker.random_element(words[:len(words)//2])
                    para = para.replace(bold_word, f"**{bold_word}**", 1)
            md_parts.append(para)
            md_parts.append("")

        md = "\n".join(md_parts)
        return md[:max_length]

    def _generate_markdown_notes(self, max_length: int) -> str:
        """Generate markdown notes with bullet list."""
        md_parts = []

        # Add heading
        md_parts.append("## Notes")
        md_parts.append("")

        # Add bullet points
        note_count = min(6, max_length // 100 + 1)
        for _ in range(note_count):
            note = self.faker.sentence(nb_words=8)
            md_parts.append(f"- {note}")

        md_parts.append("")

        # Add a note with emphasis
        important = self.faker.sentence(nb_words=10)
        md_parts.append(f"**Important:** {important}")

        md = "\n".join(md_parts)
        return md[:max_length]

    def _generate_markdown_content(self, max_length: int) -> str:
        """Generate generic markdown content."""
        md_parts = []

        # Add main heading
        title = self.faker.sentence(nb_words=4).rstrip(".")
        md_parts.append(f"# {title}")
        md_parts.append("")

        # Add introduction paragraph
        intro = self.faker.paragraph(nb_sentences=2)
        md_parts.append(intro)
        md_parts.append("")

        # Add subheading and content
        if max_length > 300:
            subtitle = self.faker.sentence(nb_words=3).rstrip(".")
            md_parts.append(f"## {subtitle}")
            md_parts.append("")
            md_parts.append(self.faker.paragraph(nb_sentences=3))
            md_parts.append("")

        # Add a list if space allows
        if max_length > 500:
            md_parts.append("### Key Points")
            md_parts.append("")
            for _ in range(3):
                item = self.faker.sentence(nb_words=6)
                md_parts.append(f"- {item}")
            md_parts.append("")

        # Add a code block if space allows
        if max_length > 700:
            md_parts.append("### Example")
            md_parts.append("")
            md_parts.append("```python")
            md_parts.append(f"value = {self.faker.random_int(min=1, max=100)}")
            md_parts.append(f'print("{self.faker.word()}")')
            md_parts.append("```")
            md_parts.append("")

        # Add a link
        if max_length > 400:
            link_text = self.faker.sentence(nb_words=3).rstrip(".")
            md_parts.append(f"For more information, see [{link_text}](#{self.faker.slug()}).")

        md = "\n".join(md_parts)
        return md[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate markdown content."""
        if not isinstance(value, str):
            return False
        if context.max_length and len(value) > context.max_length:
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.DESCRIPTION,
            FieldPattern.NOTES,
            FieldPattern.GENERIC,
        }


# Aliases for common usage
HTMLEditorHandler = TextEditorHandler  # Alias for HTML Editor field type


# Export all handler classes
__all__ = [
    # Main text handlers
    "SmallTextHandler",
    "TextHandler",
    "LongTextHandler",
    "TextEditorHandler",
    "CodeFieldHandler",
    "MarkdownHandler",
    # Aliases
    "HTMLEditorHandler",
]
