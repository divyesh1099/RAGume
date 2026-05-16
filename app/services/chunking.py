import re


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[dict]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks: list[dict] = []
    cursor = 0
    text_length = len(normalized)

    while cursor < text_length:
        end = min(text_length, cursor + max_chars)

        if end < text_length:
            window = normalized[cursor:end]
            split_points = [window.rfind("\n\n"), window.rfind("\n"), window.rfind(". ")]
            best_split = max(split_points)
            if best_split > max_chars // 2:
                end = cursor + best_split + 1

        chunk_text_value = normalized[cursor:end].strip()
        if chunk_text_value:
            chunks.append(
                {
                    "text": chunk_text_value,
                    "start_char": cursor,
                    "end_char": end,
                    "token_count": len(re.findall(r"\S+", chunk_text_value)),
                }
            )

        if end >= text_length:
            break

        next_cursor = max(end - overlap_chars, cursor + 1)
        cursor = next_cursor

    return chunks
