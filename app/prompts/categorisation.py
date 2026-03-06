from __future__ import annotations

from typing import List

from app.db.records import TopicRecord

CATEGORISATION_SYSTEM_PROMPT = """You are an expert ESG analyst. Your task is to classify a document into one or more predefined ESG scopes based on its content.

You will be given:
- Document metadata (filename, filepath, filetype)
- A document summary
- The full document content (chunked)
- A list of ESG scopes/topics with their names and instructions
- Scope-specific instructions that provide additional context on what to look for

Your output MUST be a valid JSON object with a single key "scopes" containing a ranked array of matching scopes. Each element must have the following fields:
- "name": the scope/topic name exactly as listed (e.g. "Climate Change")
- "confidence": one of "HIGH", "MEDIUM", or "LOW"
- "justification": a brief explanation of why this scope applies to the document
- "rank": integer rank starting at 1 (most relevant first)

If no scopes match the document, return {"scopes": []}.

CRITICAL: Respond ONLY with valid JSON. Do NOT wrap the response in markdown code fences. Do NOT include any text before or after the JSON object."""


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
        topics: Active topics for the project, fetched from the topics table.
                Each topic's name and instruction_text are included in the prompt.

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

    # ESG Scopes — sourced from the topics table
    sections.append("\n## ESG Scopes")
    scope_lines = [f"- {topic.name}" for topic in topics]
    sections.append("\n".join(scope_lines))

    # Scope Instructions — include instruction_text for each topic
    instructions: List[str] = []
    for topic in topics:
        if topic.instruction:
            instructions.append(f"### {topic.name}\n{topic.instruction}")

    if instructions:
        sections.append("\n## Scope Instructions")
        sections.append("\n\n".join(instructions))

    return "\n".join(sections)
