"""自绘进度条。

不用 ``QProgressBar`` 的原因：QSS 只能给 chunk 做统一圆角，无法在
「确定进度」与「不确定进度」之间平滑切换，也无法画出渐变色。

这里用 ``QPainter`` 直接绘制：

* 确定进度：按真实比例填充，并用 200ms 补间避免跳变；
* 不确定进度：一段高光循环滑动，明确表达「总量未知」而不是假百分比。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...app.bootstrap import ThemeManager

__all__ = ["ProgressBar", "IndeterminateBar"]


class ProgressBar(QWidget):
    """圆角渐变进度条。

    ``set_fraction(None)`` 会切换到不确定动画。
    """

    def __init__(self, parent: QWidget | None = None, thickness: int = 10) -> None:
        super().__init__(parent)
        self._thickness = thickness
        self._display = 0.0
        self._target = 0.0
        self._indeterminate = False
        self._phase = 0.0

        self.setFixedHeight(thickness)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animated)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        ThemeManager.instance().changed.connect(lambda _p: self.update())

    # ------------------------------------------------------------------

    def _on_animated(self, value) -> None:
        self._display = float(value)
        self.update()

    def _on_tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def set_fraction(self, fraction: float | None) -> None:
        """设置进度。``None`` 表示总量未知。"""
        if fraction is None:
            if not self._indeterminate:
                self._indeterminate = True
                self._phase = 0.0
                self._timer.start()
            self.update()
            return

        was_indeterminate = self._indeterminate
        self._indeterminate = False
        self._timer.stop()

        target = min(1.0, max(0.0, float(fraction)))
        if was_indeterminate:
            self._display = 0.0
        self._target = target
        self._animation.stop()
        self._animation.setStartValue(self._display)
        self._animation.setEndValue(target)
        self._animation.start()
        self.update()

    def reset(self) -> None:
        self._timer.stop()
        self._indeterminate = False
        self._animation.stop()
        self._display = 0.0
        self._target = 0.0
        self.update()

    @property
    def indeterminate(self) -> bool:
        return self._indeterminate

    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        palette = ThemeManager.instance().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect())
        radius = rect.height() / 2

        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        painter.fillPath(track, QColor(palette.surface_alt))

        if self._indeterminate:
            width = rect.width() * 0.28
            offset = (rect.width() + width) * self._phase - width
            chunk_rect = QRectF(offset, 0, width, rect.height())
            chunk_rect = chunk_rect.intersected(rect)
            if chunk_rect.width() > 0:
                gradient = QLinearGradient(chunk_rect.topLeft(), chunk_rect.topRight())
                start = QColor(palette.primary)
                start.setAlpha(70)
                end = QColor(palette.primary)
                end.setAlpha(230)
                gradient.setColorAt(0.0, start)
                gradient.setColorAt(1.0, end)
                path = QPainterPath()
                path.addRoundedRect(chunk_rect, radius, radius)
                painter.fillPath(path, gradient)
        else:
            width = rect.width() * self._display
            if width > 0.5:
                fill = QRectF(0, 0, max(width, rect.height()), rect.height())
                gradient = QLinearGradient(fill.topLeft(), fill.topRight())
                gradient.setColorAt(0.0, QColor(palette.primary))
                gradient.setColorAt(1.0, QColor(palette.primary_hover))
                path = QPainterPath()
                path.addRoundedRect(fill, radius, radius)
                painter.fillPath(path, gradient)

        painter.end()


class IndeterminateBar(ProgressBar):
    """始终不确定的进度条（用于无法获知总量的短操作）。"""

    def __init__(self, parent: QWidget | None = None, thickness: int = 10) -> None:
        super().__init__(parent, thickness)
        self.set_fraction(None)
