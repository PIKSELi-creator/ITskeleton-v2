from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


WIDTH = 1080
HEIGHT = 1920
FPS = 30


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "FFmpeg не найден. Установи FFmpeg в окружении Amvera."
        )
    return path


def _find_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise RuntimeError(
            "FFprobe не найден. Установи FFmpeg в окружении Amvera."
        )
    return path


def ffprobe(path: str | Path) -> dict[str, Any]:
    """
    Получает базовую информацию о видеофайле.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    ffprobe_bin = _find_ffprobe()

    result = _run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ]
    )

    data = json.loads(result.stdout or "{}")
    fmt = data.get("format", {})

    duration = fmt.get("duration")
    size = fmt.get("size")

    return {
        "duration_seconds": float(duration) if duration else None,
        "size_bytes": int(size) if size else None,
        "path": str(path),
    }


def _check_images(image_files: Iterable[str | Path]) -> list[Path]:
    images = [Path(p) for p in image_files]

    if not images:
        raise ValueError("Не переданы изображения для рендера.")

    for image in images:
        if not image.exists():
            raise FileNotFoundError(
                f"Изображение не найдено: {image}"
            )

    return images


def _image_duration(image_count: int) -> float:
    """
    Базовая длительность одного кадра.

    Для 8 изображений получается примерно 38.4 секунды.
    """
    if image_count <= 0:
        return 5.0

    return 38.4 / image_count


def render_video_file(
    image_files: list[str | Path],
    audio_file: str | Path | None,
    output: str | Path,
) -> dict[str, Any]:
    """
    Создаёт вертикальный MP4 из набора изображений.

    Параметры:
        image_files — изображения кадров.
        audio_file  — необязательный аудиофайл.
        output      — путь итогового MP4.

    Формат:
        1080x1920
        30 FPS
        H.264
        AAC при наличии аудио
    """

    images = _check_images(image_files)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if audio_file is not None:
        audio_file = Path(audio_file)

        if not audio_file.exists():
            raise FileNotFoundError(
                f"Аудиофайл не найден: {audio_file}"
            )

    ffmpeg = _find_ffmpeg()

    duration = _image_duration(len(images))

    with tempfile.TemporaryDirectory(prefix="itskeleton_render_") as temp_dir:
        temp = Path(temp_dir)

        # Создаём concat-файл для FFmpeg.
        concat_file = temp / "images.txt"

        lines: list[str] = []

        for image in images:
            # Абсолютный путь и экранирование одинарных кавычек.
            image_path = str(image.resolve()).replace("'", "'\\''")

            lines.append(f"file '{image_path}'")
            lines.append(f"duration {duration:.4f}")

        # Последний кадр должен быть указан ещё раз,
        # иначе FFmpeg может не удержать его длительность.
        last_image = str(images[-1].resolve()).replace("'", "'\\''")
        lines.append(f"file '{last_image}'")

        concat_file.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        command = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
        ]

        if audio_file is not None:
            command.extend(
                [
                    "-i",
                    str(audio_file),
                ]
            )

        # Масштабируем изображение до вертикального 9:16,
        # не растягивая его.
        video_filter = (
            "scale=1080:1920:"
            "force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )

        command.extend(
            [
                "-vf",
                video_filter,
                "-r",
                str(FPS),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
            ]
        )

        if audio_file is not None:
            command.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                ]
            )
        else:
            command.extend(
                [
                    "-an",
                ]
            )

        command.extend(
            [
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

        try:
            _run(command)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "FFmpeg не смог создать видео:\n"
                f"{exc.stderr}"
            ) from exc

    if not output.exists():
        raise RuntimeError(
            f"FFmpeg завершился, но файл не создан: {output}"
        )

    probe = ffprobe(output)

    return {
        "ok": True,
        "file": str(output),
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "duration_seconds": probe["duration_seconds"],
        "size_bytes": probe["size_bytes"],
    }