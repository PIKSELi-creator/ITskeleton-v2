from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from renderer import ffprobe, render_video_file


BASE_DIR = Path(__file__).resolve().parent

VIDEO_OUTPUT_DIR = Path(
    os.getenv("VIDEO_OUTPUT_DIR", "/data/videos")
)

VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def video_dir() -> Path:
    """Возвращает директорию для готовых видео."""
    VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return VIDEO_OUTPUT_DIR


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def create_script(
    topic: str,
    language: str = "python",
    duration: int = 40,
) -> dict[str, Any]:
    """
    Создаёт базовую структуру сценария.
    """

    topic = topic.strip()

    if not topic:
        raise ValueError("Тема видео не указана.")

    return {
        "topic": topic,
        "language": language,
        "duration": duration,
        "hook": f"Разберём {topic} за несколько секунд.",
        "explanation": (
            f"В этом видео простыми словами объясняется, "
            f"как работает {topic} в {language}."
        ),
        "example": (
            f"# Пример по теме: {topic}\n"
            f"print('Hello, ITskeleton!')"
        ),
        "ending": "Подписывайся на ITskeleton для новых видео по Python.",
    }


def create_storyboard(
    script: dict[str, Any],
    image_files: list[str] | None = None,
) -> dict[str, Any]:
    """
    Создаёт простой storyboard для вертикального ролика.
    """

    topic = script.get("topic", "Python")

    scenes = [
        {
            "id": 1,
            "type": "hook",
            "text": script.get("hook", ""),
        },
        {
            "id": 2,
            "type": "explanation",
            "text": script.get("explanation", ""),
        },
        {
            "id": 3,
            "