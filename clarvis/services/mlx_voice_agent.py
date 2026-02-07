"""MLX voice agent — local on-device inference via genlm + mlx-lm.

Provides the same interface as VoiceAgent (duck-typed) so the
VoiceCommandOrchestrator works with either provider unchanged.

The model is loaded once and kept alive permanently (no idle timeout).
Maintains a rolling chat history for multi-turn conversations.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator

import mlx.core as mx
from mlx_lm.generate import generate_step
from mlx_lm.sample_utils import make_sampler

from genlm.backend.llm.mlx import AsyncMlxLM

logger = logging.getLogger(__name__)

# Simplified prompt for local MLX models — no JSON, no tool use.
MLX_SYSTEM_PROMPT = """\
You are Clarvis, a voice assistant. You receive transcribed speech and respond conversationally.

Rules:
- Keep responses to 1-3 sentences unless asked for more.
- Act on commands directly — don't ask for clarification.
- Never use markdown formatting — your responses are spoken aloud via TTS.
- A <context> block may precede the user's message with current situational data (weather, time, music). Use it to inform your responses naturally — don't mention the context block explicitly.
- Be helpful, concise, and friendly.\
"""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Debug print helper — goes to daemon.err.log
def _dbg(msg: str) -> None:
    import sys
    print(f"[MLX-DBG] {msg}", file=sys.stderr, flush=True)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from reasoning model output."""
    stripped = _THINK_RE.sub("", text).strip()
    # If think block was never closed, drop everything from <think> onward
    if "<think>" in stripped:
        stripped = stripped.split("<think>", 1)[0].strip()
    return stripped


class MLXVoiceAgent:
    """Local MLX voice agent using genlm backend.

    Lifecycle: model loads on first ensure_connected() and stays resident.
    No idle timeout — the model is kept alive permanently.
    """

    def __init__(
        self,
        event_loop: asyncio.AbstractEventLoop,
        model_name: str = "mlx-community/Qwen2.5-7B-Instruct-4bit",
        temperature: float = 0.7,
        max_tokens: int = 512,
        max_history_turns: int = 10,
    ):
        self._loop = event_loop
        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_history_turns = max_history_turns
        self._history: list[dict[str, str]] = []
        self._llm: AsyncMlxLM | None = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._interrupted = False
        _dbg(f"MLXVoiceAgent created: model={model_name}, temp={temperature}, max_tokens={max_tokens}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_connected(self) -> None:
        """Load the MLX model if not already loaded."""
        if self._connected:
            _dbg("ensure_connected: already connected")
            return
        async with self._lock:
            if self._connected:
                return
            _dbg(f"ensure_connected: loading model {self._model_name}...")
            t0 = time.monotonic()
            # Model loading is CPU/GPU-bound; run in thread to avoid blocking loop
            self._llm = await self._loop.run_in_executor(
                None, AsyncMlxLM.from_name, self._model_name
            )
            self._connected = True
            _dbg(f"ensure_connected: model loaded in {time.monotonic() - t0:.1f}s")

    async def disconnect(self) -> None:
        """No-op — model stays loaded permanently."""
        pass

    async def shutdown(self) -> None:
        """Free model memory at daemon exit."""
        async with self._lock:
            if self._llm is not None:
                self._llm = None
                self._connected = False
                _dbg("shutdown: model unloaded")

    @property
    def connected(self) -> bool:
        return self._connected

    def clear_history(self) -> None:
        """Clear conversation history (e.g. between voice sessions)."""
        self._history.clear()
        _dbg("Chat history cleared")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def send(self, text: str) -> AsyncIterator[str]:
        """Send a voice command and yield response text chunks.

        Maintains a rolling chat history. Each call appends the user
        message, generates with full history, and appends the assistant
        response. Old turns are trimmed when history exceeds max_history_turns.
        """
        _dbg(f"send() called with text: {text[:80]!r}")
        try:
            await self.ensure_connected()
            assert self._llm is not None

            self._interrupted = False

            # Append user turn and trim old history
            self._history.append({"role": "user", "content": text})
            if len(self._history) > self._max_history_turns:
                self._history = self._history[-self._max_history_turns:]

            # Build full message list: system prompt + conversation history
            messages = [
                {"role": "system", "content": MLX_SYSTEM_PROMPT},
                *self._history,
            ]
            _dbg(f"History: {len(self._history)} messages ({len(self._history)//2} exchanges)")

            # Apply model's chat template
            tokenizer = self._llm.tokenizer
            try:
                prompt_str = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            except Exception as e:
                _dbg(f"Chat template failed with system role: {e}, using user-only")
                combined = f"{MLX_SYSTEM_PROMPT}\n\n{text}"
                messages = [{"role": "user", "content": combined}]
                prompt_str = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )

            prompt_ids = tokenizer.encode(prompt_str)
            _dbg(f"Prompt: {len(prompt_ids)} tokens")
            prompt_array = mx.array(prompt_ids)

            # Stream tokens via generate_step
            sampler = make_sampler(temp=self._temperature)
            eos_id = tokenizer.eos_token_id

            _dbg("Starting generate_step...")
            t0 = time.monotonic()
            token_gen = generate_step(
                prompt_array,
                self._llm.mlx_lm_model,
                max_tokens=self._max_tokens,
                sampler=sampler,
            )

            generated_ids: list[int] = []

            for token_id, _ in token_gen:
                if self._interrupted:
                    _dbg(f"Interrupted at token {len(generated_ids)}")
                    break
                if token_id == eos_id:
                    _dbg(f"EOS at token {len(generated_ids)}")
                    break
                generated_ids.append(token_id)
                # Yield control periodically
                if len(generated_ids) % 4 == 0:
                    await asyncio.sleep(0)

            t1 = time.monotonic()
            _dbg(f"Generated {len(generated_ids)} tokens in {t1 - t0:.1f}s")

            # Decode complete output, strip <think>...</think> blocks
            full_text = tokenizer.decode(generated_ids) if generated_ids else ""
            _dbg(f"Raw output ({len(full_text)} chars): {full_text[:100]!r}")
            response = _strip_think_tags(full_text)
            _dbg(f"After strip_think ({len(response)} chars): {response[:100]!r}")

            if response:
                # Store the clean response in history for future turns
                self._history.append({"role": "assistant", "content": response})
                yield response
            else:
                _dbg("WARNING: empty response after stripping think tags")
                # Remove the user message since we got no response
                self._history.pop()

        except Exception as e:
            _dbg(f"EXCEPTION in send(): {type(e).__name__}: {e}")
            import traceback
            _dbg(traceback.format_exc())
            raise

    async def interrupt(self) -> None:
        """Signal the generation loop to stop."""
        _dbg("interrupt() called")
        self._interrupted = True
