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
        "ending": "Подписывайся на ITskeleton для новых видео по другим языкам и др.",
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
            "type": "example",
            "text": script.get("example", ""),
        },
        {
            "id": 4,
            "type": "ending",
            "text": script.get("ending", ""),
        },
    ]

    if image_files:
        for index, image in enumerate(image_files):
            if index < len(scenes):
                scenes[index]["image"] = str(image)

    return {
        "topic": topic,
        "scenes": scenes,
    }


def create_edit_plan(
    storyboard: dict[str, Any],
    audio_file: str | None = None,
) -> dict[str, Any]:
    """
    Создаёт план монтажа.
    """

    scenes = storyboard.get("scenes", [])

    return {
        "format": "vertical",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "codec": "h264",
        "audio": audio_file,
        "scenes": scenes,
        "transitions": "cut",
    }


def render_from_plan(
    plan: dict[str, Any],
    output: str | Path | None = None,
) -> dict[str, Any]:
    """
    Рендерит видео согласно edit plan.
    """

    scenes = plan.get("scenes", [])

    image_files: list[str] = []

    for scene in scenes:
        image = scene.get("image")

        if image:
            image_files.append(str(image))

    if not image_files:
        raise ValueError(
            "В edit plan нет изображений для рендера."
        )

    audio_file = plan.get("audio")

    if output is None:
        output = video_dir() / "itskeleton_video.mp4"
    else:
        output = Path(output)

    return render_video_file(
        image_files=image_files,
        audio_file=audio_file,
        output=output,
    )


def run_pipeline(
    topic: str,
    image_files: list[str] | None = None,
    audio_file: str | None = None,
    output: str | Path | None = None,
    language: str = "python",
    duration: int = 40,
) -> dict[str, Any]:
    """
    Полный pipeline:

    тема
      ↓
    сценарий
      ↓
    storyboard
      ↓
    edit plan
      ↓
    FFmpeg
      ↓
    MP4
    """

    script = create_script(
        topic=topic,
        language=language,
        duration=duration,
    )

    storyboard = create_storyboard(
        script=script,
        image_files=image_files,
    )

    plan = create_edit_plan(
        storyboard=storyboard,
        audio_file=audio_file,
    )

    result = render_from_plan(
        plan=plan,
        output=output,
    )

    return {
        "ok": True,
        "script": script,
        "storyboard": storyboard,
        "edit_plan": plan,
        "video": result,
    }


def save_pipeline_result(
    result: dict[str, Any],
    filename: str = "pipeline_result.json",
) -> Path:
    """
    Сохраняет результат pipeline в JSON.
    """

    path = video_dir() / filename

    path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return path


def get_video_info(path: str | Path) -> dict[str, Any]:
    """
    Возвращает информацию о готовом видео.
    """

    return ffprobe(path)