from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class CapCutAdapter:
    """
    Адаптер для работы с CapCut.

    В режиме auto пытается использовать CapCut, если он доступен.
    Если CapCut недоступен, pipeline может продолжить работу
    через собственный FFmpeg-рендерер.
    """

    def __init__(
        self,
        mode: str | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.mode = (
            mode
            or os.getenv("CAPCUT_MODE", "auto")
        ).lower()

        self.output_dir = Path(
            output_dir
            or os.getenv(
                "VIDEO_OUTPUT_DIR",
                "/data/videos",
            )
        )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    @property
    def available(self) -> bool:
        """
        Проверяет доступность CapCut.

        На сервере Amvera CapCut обычно недоступен,
        поэтому возвращается False.
        """

        return False

    def status(self) -> dict[str, Any]:
        """
        Возвращает состояние адаптера.
        """

        return {
            "mode": self.mode,
            "available": self.available,
            "output_dir": str(self.output_dir),
        }

    def create_project(
        self,
        project_name: str,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
    ) -> dict[str, Any]:
        """
        Создаёт описание проекта.

        Реальный проект CapCut на сервере не создаётся.
        """

        if not project_name.strip():
            raise ValueError(
                "Название проекта не может быть пустым."
            )

        return {
            "name": project_name,
            "width": width,
            "height": height,
            "fps": fps,
            "mode": self.mode,
            "capcut_available": self.available,
        }

    def import_media(
        self,
        project: dict[str, Any],
        files: list[str | Path],
    ) -> dict[str, Any]:
        """
        Добавляет медиафайлы в описание проекта.
        """

        media = []

        for file in files:
            path = Path(file)

            if not path.exists():
                raise FileNotFoundError(
                    f"Медиафайл не найден: {path}"
                )

            media.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size": path.stat().st_size,
                }
            )

        project = dict(project)
        project["media"] = media

        return project

    def export(
        self,
        project: dict[str, Any],
        output: str | Path | None = None,
    ) -> Path:
        """
        Экспортирует проект.

        Сам CapCut на сервере не используется.
        Этот метод оставлен для совместимости с pipeline.
        """

        if output is None:
            output = (
                self.output_dir
                / f"{project.get('name', 'itskeleton')}.mp4"
            )

        output = Path(output)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        raise RuntimeError(
            "CapCut недоступен в серверном окружении. "
            "Используй FFmpeg renderer."
        )

    def is_auto_mode(self) -> bool:
        return self.mode == "auto"

    def is_disabled(self) -> bool:
        return self.mode in {
            "off",
            "disabled",
            "none",
        }

    def is_enabled(self) -> bool:
        return not self.is_disabled()