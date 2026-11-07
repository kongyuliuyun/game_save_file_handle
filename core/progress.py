"""进度上报与取消机制。

这是修复「进度条虚假」的地基：所有阶段都必须给出**可验证的分子与分母**，
界面只在拿到真实比例时显示百分比，否则显示不确定状态 + 实时活动量。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Iterator, TypeVar

from .errors import TaskCancelled

__all__ = [
    "Stage",
    "ProgressEvent",
    "ProgressCallback",
    "CancellationToken",
    "SpeedMeter",
    "TaskContext",
    "throttled",
]

T = TypeVar("T")


class Stage(str, Enum):
    """流水线阶段。顺序即执行顺序。"""

    IDLE = "idle"
    SCAN = "scan"
    COPY = "copy"
    PACK = "pack"
    UPLOAD = "upload"
    CLEANUP = "cleanup"
    DONE = "done"

    @property
    def label(self) -> str:
        return {
            Stage.IDLE: "空闲",
            Stage.SCAN: "扫描存档",
            Stage.COPY: "复制文件",
            Stage.PACK: "压缩打包",
            Stage.UPLOAD: "上传网盘",
            Stage.CLEANUP: "清理临时文件",
            Stage.DONE: "已完成",
        }[self]


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """一次进度采样。

    ``total <= 0`` 或 ``indeterminate=True`` 时表示分母未知，
    界面必须显示不确定进度而不是伪造百分比。
    """

    stage: Stage
    done: float = 0.0
    total: float = 0.0
    unit: str = "files"
    message: str = ""
    detail: str = ""
    indeterminate: bool = False

    @property
    def fraction(self) -> float | None:
        if self.indeterminate or self.total <= 0:
            return None
        return min(1.0, max(0.0, self.done / self.total))


ProgressCallback = Callable[[ProgressEvent], None]


def _noop(_: ProgressEvent) -> None:
    return None


class CancellationToken:
    """线程安全的取消信号。所有耗时循环都必须在边界处调用 :meth:`check`。"""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise TaskCancelled()


class SpeedMeter:
    """滑动窗口速率估算，用于显示实时速度与剩余时间。

    直接对瞬时速度做平均会剧烈抖动；这里取最近 ``window`` 秒内的
    累计量变化，既平滑又能反映真实吞吐。
    """

    __slots__ = ("_window", "_samples")

    def __init__(self, window: float = 4.0) -> None:
        self._window = window
        self._samples: deque[tuple[float, float]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def update(self, done: float, *, now: float | None = None) -> float:
        """记录一次采样并返回当前速度（单位/秒）。"""
        moment = time.monotonic() if now is None else now
        self._samples.append((moment, done))
        cutoff = moment - self._window
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        first_t, first_done = self._samples[0]
        elapsed = moment - first_t
        if elapsed <= 0.05:
            return 0.0
        speed = (done - first_done) / elapsed
        return max(0.0, speed)

    @staticmethod
    def eta(total: float, done: float, speed: float) -> float | None:
        """根据速度推算剩余秒数；无法估算时返回 ``None``。"""
        if total <= 0 or speed <= 0:
            return None
        remaining = total - done
        if remaining <= 0:
            return 0.0
        return remaining / speed


class TaskContext:
    """把「取消令牌 + 进度回调 + 速率计」打包，交给各阶段函数使用。"""

    __slots__ = ("token", "emit", "meter")

    def __init__(
        self,
        token: CancellationToken | None = None,
        emit: ProgressCallback | None = None,
    ) -> None:
        self.token = token or CancellationToken()
        self.emit = emit or _noop
        self.meter = SpeedMeter()

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def check(self) -> None:
        self.token.check()

    def report(
        self,
        stage: Stage,
        done: float = 0.0,
        total: float = 0.0,
        *,
        unit: str = "files",
        message: str = "",
        detail: str = "",
    ) -> None:
        self.emit(
            ProgressEvent(
                stage=stage,
                done=done,
                total=total,
                unit=unit,
                message=message,
                detail=detail,
                indeterminate=total <= 0,
            )
        )

    def activity(
        self, stage: Stage, message: str, detail: str = ""
    ) -> None:
        """上报一次「正在进行但总量未知」的活动，避免界面看起来假死。"""
        self.emit(
            ProgressEvent(
                stage=stage,
                message=message,
                detail=detail,
                indeterminate=True,
            )
        )


def throttled(
    callback: ProgressCallback, min_interval: float = 0.05
) -> ProgressCallback:
    """对进度回调做时间节流，防止高频事件把界面事件循环淹没。"""
    lock = threading.Lock()
    state = {"last": 0.0}

    def wrapper(event: ProgressEvent) -> None:
        now = time.monotonic()
        with lock:
            if event.fraction is not None and now - state["last"] < min_interval:
                if event.fraction < 1.0:
                    return
            state["last"] = now
        callback(event)

    return wrapper


def iter_with_progress(
    items: Iterable[T],
    total: int,
    ctx: TaskContext,
    stage: Stage,
    *,
    unit: str = "files",
    message: str = "",
) -> Iterator[T]:
    """带取消检查与进度上报的迭代器。"""
    for index, item in enumerate(items, start=1):
        ctx.check()
        yield item
        ctx.report(stage, index, total, unit=unit, message=message)
