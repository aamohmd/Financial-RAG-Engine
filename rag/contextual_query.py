from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api import ChatTurn


def build_contextual_query(question: str, history: list["ChatTurn"], max_turns: int = 6) -> str:
    recent_turns = history[-max_turns:]
    formatted_turns: list[str] = []

    for turn in recent_turns:
        content = " ".join(turn.content.split()).strip()
        if not content:
            continue

        if len(content) > 320:
            content = f"{content[:317]}..."

        speaker = "User" if turn.role == "user" else "Assistant"
        formatted_turns.append(f"{speaker}: {content}")

    if not formatted_turns:
        return question

    history_block = "\n".join(formatted_turns)
    return (
        "Conversation history (oldest to newest):\n"
        f"{history_block}\n\n"
        f"Current user question: {question}"
    )