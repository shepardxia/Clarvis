"""Generate whimsical verbs describing Claude's activity using DSPy."""

import os
from pathlib import Path
import dspy

# Load .env
_env = Path(__file__).parent.parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SYSTEM_PROMPT = """Analyze this message and come up with a single positive, cheerful and delightful verb in gerund form that's related to the message. Only include the word with no other text or punctuation. The word should have the first letter capitalized. Add some whimsy and surprise to entertain the user. Ensure the word is highly relevant to the user's message. Synonyms are welcome, including obscure words. Be careful to avoid words that might look alarming or concerning to the software engineer seeing it as a status notification, such as Connecting, Disconnecting, Retrying, Lagging, Freezing, etc. NEVER use a destructive word, such as Terminating, Killing, Deleting, Destroying, Stopping, Exiting, or similar. NEVER use a word that may be derogatory, offensive, or inappropriate in a non-coding context, such as Penetrating."""


def generate_whimsy_verb(context: str) -> str:
    """Generate a whimsical gerund verb for the given context."""
    lm = dspy.LM(
        model="anthropic/claude-haiku-4-5",
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_tokens=20,
        temperature=0.9,
    )

    response = lm(messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context[:2000]},  # Truncate
    ])

    return response[0].strip().split()[0].title()


if __name__ == "__main__":
    context = "Debugging a null pointer exception in the auth module"
    for i in range(5):
        print(generate_whimsy_verb(context))
