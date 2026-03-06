from __future__ import annotations

from typing import List

from app.db.records import TopicRecord

CATEGORISATION_SYSTEM_PROMPT = """You are an expert ESG analyst. Your task is to classify a document into one or more predefined ESG scopes based on its content.

You will be given:
- Document metadata (filename, filepath, filetype)
- A document summary
- The full document content (chunked)
- A list of ESG scopes with their codes and names
- Optional scope-specific instructions that provide additional context

Your output MUST be a valid JSON object with a single key "scopes" containing a ranked array of matching scopes. Each element must have the following fields:
- "code": the scope code (e.g. "S01")
- "name": the scope name (e.g. "Climate Change")
- "confidence": one of "HIGH", "MEDIUM", or "LOW"
- "justification": a brief explanation of why this scope applies to the document
- "rank": integer rank starting at 1 (most relevant first)

If no scopes match the document, return {"scopes": []}.

CRITICAL: Respond ONLY with valid JSON. Do NOT wrap the response in markdown code fences. Do NOT include any text before or after the JSON object."""

ESG_SCOPES = [
    ("S01", "Climate Change"),
    ("S02", "Natural Capital"),
    ("S03", "Pollution & Waste"),
    ("S04", "Environmental Opportunities"),
    ("S05", "Human Capital"),
    ("S06", "Product Liability"),
    ("S07", "Social Opportunities"),
    ("S08", "Stakeholder Opposition"),
    ("S09", "Corporate Governance"),
    ("S10", "Corporate Behaviour"),
    ("S11", "ESG Integration"),
    ("S12", "Energy Management"),
    ("S13", "Water & Wastewater"),
    ("S14", "Biodiversity"),
    ("S15", "Supply Chain"),
    ("S16", "Health & Safety"),
    ("S17", "Community Relations"),
    ("S18", "Data Privacy & Security"),
    ("S19", "Responsible Investment"),
]

# Build a lookup dict for quick name matching (lowercase -> code)
_SCOPE_NAME_TO_CODE = {name.lower(): code for code, name in ESG_SCOPES}


def build_categorisation_prompt(
    file_name: str,
    file_path: str,
    file_type: str,
    summary_text: str,
    chunks: List[str],
    topics: List[TopicRecord],
) -> str:
    """Build the user prompt for ESG scope categorisation.

    Args:
        file_name: Original filename of the document.
        file_path: Storage path of the document.
        file_type: MIME type or file extension (e.g. "pdf").
        summary_text: AI-generated summary of the document.
        chunks: All document chunks ordered by chunk_index.
        topics: Active topics for the project. Topic instructions are injected
                into the prompt when the topic name matches an ESG scope name
                (case-insensitive), implementing EINST-01.

    Returns:
        Assembled user prompt string ready to pass to the LLM.
    """
    sections: List[str] = []

    # Document Metadata
    sections.append("## Document Metadata")
    sections.append(f"Filename: {file_name}")
    sections.append(f"Filepath: {file_path}")
    sections.append(f"Filetype: {file_type}")

    # Document Summary
    sections.append("\n## Document Summary")
    sections.append(summary_text)

    # Document Content
    sections.append("\n## Document Content")
    chunk_parts = [f"Chunk {i + 1}:\n{chunk}" for i, chunk in enumerate(chunks)]
    sections.append("\n\n".join(chunk_parts))

    # ESG Scopes
    sections.append("\n## ESG Scopes")
    scope_lines = [f"{code}: {name}" for code, name in ESG_SCOPES]
    sections.append("\n".join(scope_lines))

    # Scope Instructions (EINST-01) — inject topic instructions for matching scopes
    matching_instructions: List[str] = []
    for topic in topics:
        scope_code = _SCOPE_NAME_TO_CODE.get(topic.name.lower())
        if scope_code is not None:
            matching_instructions.append(
                f"### {scope_code}: {topic.name}\n{topic.instruction}"
            )

    if matching_instructions:
        sections.append("\n## Scope Instructions")
        sections.append("\n\n".join(matching_instructions))

    return "\n".join(sections)
