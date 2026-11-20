import sys
import os
import time
import logging
import json
import threading
from pathlib import Path
from collections import deque

import mss
import numpy as np
from PIL import Image
from pynput import keyboard as pynput_keyboard
from rapidocr_onnxruntime import RapidOCR
from deep_translator import GoogleTranslator

from PySide6.QtCore import Qt, QTimer, QRect, QPoint, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPixmap, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QFrame, QRubberBand, QMessageBox, QSystemTrayIcon, QMenu
)

APP_NAME = "RobRun Translator HUD"

def configure_logging():
    base_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    log_dir = base_dir / "RobRunTranslatorHUD"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )
    return log_file

LOG_PATH = configure_logging()


class WorkerSignals(QObject):
    result = Signal(str, str)
    error = Signal(str)
    info = Signal(str)
    pause_hotkey = Signal()
    select_hotkey = Signal()
    visibility_hotkey = Signal()
    clear_hotkey = Signal()


class RegionSelector(QWidget):
    selected = Signal(QRect)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry() if screen else QRect(0, 0, 1920, 1080))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.origin = QPoint()
        self.band = QRubberBand(QRubberBand.Rectangle, self)
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))
        painter.setPen(QPen(QColor("#38e8ff"), 2))
        painter.setFont(QFont("Segoe UI", 15, QFont.Bold))
        painter.drawText(
            30, 50,
            "Kéo chuột chọn vùng hội thoại / phụ đề — nhấn ESC để hủy"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.position().toPoint()
            self.band.setGeometry(QRect(self.origin, self.origin))
            self.band.show()

    def mouseMoveEvent(self, event):
        if self.band.isVisible():
            self.band.setGeometry(
                QRect(self.origin, event.position().toPoint()).normalized()
            )

    def mouseReleaseEvent(self, event):
        rect = self.band.geometry().normalized()
        self.band.hide()
        if rect.width() > 30 and rect.height() > 20:
            screen_geo = self.geometry()
            rect.translate(screen_geo.topLeft())
            self.selected.emit(rect)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


class Hud(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.Tool | Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(390)
        self.resize(520, 225)

        self.region = None
        self.paused = False
        self.busy = False
        self.error_retry_after = 0.0
        self.last_source = ""
        self.last_source_key = ""
        self.candidate_source = ""
        self.candidate_count = 0
        self.min_request_interval = 6.0
        self.daily_request_limit = 160
        self.last_request_at = 0.0
        self.translation_cache = {}
        self.daily_request_count = 0
        self.daily_counter_date = time.strftime("%Y-%m-%d")
        self.state_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RobRunTranslatorHUD" / "state.json"
        self.load_state()
        self.history = deque(maxlen=30)
        self.ocr = None
        self.translator = GoogleTranslator(source="en", target="vi")
        self.drag_pos = None
        self.selector = None
        self.key_listener = None

        self.signals = WorkerSignals()
        self.signals.result.connect(self.show_translation)
        self.signals.error.connect(self.show_error)
        self.signals.info.connect(self.set_scan_status)
        self.signals.pause_hotkey.connect(self.toggle_pause)
        self.signals.select_hotkey.connect(self.select_region)
        self.signals.visibility_hotkey.connect(self.toggle_hud)
        self.signals.clear_hotkey.connect(self.clear_text)

        self.build_ui()
        self.build_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(1400)

        self.start_global_hotkeys()

    def build_ui(self):
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        self.panel.setStyleSheet("""
            QFrame#panel {
                background: rgba(8, 13, 24, 232);
                border: 1px solid #24d9f2;
                border-radius: 14px;
            }
            QLabel { color: #eafaff; }
            QPushButton {
                color: #eafaff;
                background: #14283a;
                border: 1px solid #246178;
                border-radius: 8px;
                padding: 6px 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: #1d4960; }
        """)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.brand = QLabel("◈ ROBRUN TRANSLATOR")
        self.brand.setStyleSheet(
            "color:#39e8ff;font-size:13px;font-weight:800;letter-spacing:1px;"
        )
        top.addWidget(self.brand)
        top.addStretch()

        self.status = QLabel("● CHƯA CHỌN VÙNG")
        self.status.setStyleSheet(
            "color:#ffd166;font-size:10px;font-weight:700;"
        )
        top.addWidget(self.status)

        self.min_btn = QPushButton("—")
        self.min_btn.setFixedWidth(32)
        self.min_btn.setToolTip("Ẩn HUD; bấm biểu tượng khay hệ thống để mở lại")
        self.min_btn.clicked.connect(self.hide)
        top.addWidget(self.min_btn)
        root.addLayout(top)

        self.original = QLabel("EN  Chưa có nội dung được nhận diện")
        self.original.setWordWrap(True)
        self.original.setStyleSheet("color:#9db5c7;font-size:12px;")
        root.addWidget(self.original)

        self.translation = QLabel("VI  Bản dịch tiếng Việt sẽ hiển thị tại đây")
        self.translation.setWordWrap(True)
        self.translation.setMinimumHeight(70)
        self.translation.setStyleSheet(
            "color:#ffffff;font-size:19px;font-weight:700;"
        )
        root.addWidget(self.translation)

        bottom = QHBoxLayout()
        self.region_btn = QPushButton("⌖ Chọn vùng  F7")
        self.region_btn.clicked.connect(self.select_region)
        self.pause_btn = QPushButton("Ⅱ Tạm dừng  F6")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.clear_btn = QPushButton("Xóa  F9")
        self.clear_btn.clicked.connect(self.clear_text)
        bottom.addWidget(self.region_btn)
        bottom.addWidget(self.pause_btn)
        bottom.addWidget(self.clear_btn)
        root.addLayout(bottom)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)

    def build_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#081320"))
        painter.setPen(QPen(QColor("#39e8ff"), 4))
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QPen(QColor("#39e8ff"), 3))
        painter.setFont(QFont("Segoe UI", 23, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "R")
        painter.end()

        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        show_action = QAction("Hiện HUD", self)
        show_action.triggered.connect(self.show_hud)
        choose_action = QAction("Chọn vùng nhận diện (F7)", self)
        choose_action.triggered.connect(self.select_region)
        pause_action = QAction("Tạm dừng / tiếp tục (F6)", self)
        pause_action.triggered.connect(self.toggle_pause)
        quit_action = QAction("Thoát phần mềm", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(choose_action)
        menu.addAction(pause_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick or reason == QSystemTrayIcon.Trigger:
            self.show_hud()

    def start_global_hotkeys(self):
        def on_press(key):
            if key == pynput_keyboard.Key.f6:
                self.signals.pause_hotkey.emit()
            elif key == pynput_keyboard.Key.f7:
                self.signals.select_hotkey.emit()
            elif key == pynput_keyboard.Key.f8:
                self.signals.visibility_hotkey.emit()
            elif key == pynput_keyboard.Key.f9:
                self.signals.clear_hotkey.emit()

        try:
            self.key_listener = pynput_keyboard.Listener(on_press=on_press)
            self.key_listener.daemon = True
            self.key_listener.start()
        except Exception:
            self.key_listener = None

    def show_hud(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_hud(self):
        if self.isVisible():
            self.hide()
        else:
            self.show_hud()

    def resizeEvent(self, event):
        self.panel.setGeometry(self.rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if self.drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def select_region(self):
        if self.selector is not None:
            self.selector.close()
        self.selector = RegionSelector()
        self.selector.selected.connect(self.set_region)
        self.selector.show()
        self.selector.raise_()

    def set_region(self, rect):
        self.region = rect
        self.status.setText("● ĐANG QUÉT")
        self.status.setStyleSheet(
            "color:#55efb0;font-size:10px;font-weight:700;"
        )

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.setText(
            "▶ Tiếp tục  F6" if self.paused else "Ⅱ Tạm dừng  F6"
        )
        if self.paused:
            self.status.setText("● TẠM DỪNG")
        elif self.region:
            self.status.setText("● ĐANG QUÉT")
        else:
            self.status.setText("● CHƯA CHỌN VÙNG")

    def clear_text(self):
        self.original.setText("EN  Chưa có nội dung được nhận diện")
        self.translation.setText("VI  Bản dịch tiếng Việt sẽ hiển thị tại đây")
        self.last_source = ""
        self.last_source_key = ""

    def normalize_source(self, text):
        return " ".join((text or "").split()).casefold()

    def load_state(self):
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.translation_cache = data.get("cache", {})
                today = time.strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self.daily_request_count = int(data.get("request_count", 0))
                    self.last_request_at = float(data.get("last_request_at", 0.0))
                else:
                    self.daily_counter_date = today
                    self.daily_request_count = 0
                    self.last_request_at = 0.0
                logging.info(
                    "Loaded translation cache (%d entries); daily requests=%d",
                    len(self.translation_cache), self.daily_request_count
                )
        except Exception:
            logging.exception("Could not load app state")
            self.translation_cache = {}
            self.daily_request_count = 0
            self.last_request_at = 0.0

    def save_state(self):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "date": self.daily_counter_date,
                "request_count": self.daily_request_count,
                "last_request_at": self.last_request_at,
                "cache": self.translation_cache,
            }
            temp_path = self.state_path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8"
            )
            temp_path.replace(self.state_path)
        except Exception:
            logging.exception("Could not save app state")

    def refresh_daily_counter(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.daily_counter_date:
            self.daily_counter_date = today
            self.daily_request_count = 0
            self.last_request_at = 0.0
            self.save_state()

    def scan(self):
        if self.paused or self.busy or self.region is None:
            return
        if time.monotonic() < self.error_retry_after:
            return
        self.busy = True
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        stage = "Khởi tạo mô hình OCR"
        try:
            if self.ocr is None:
                self.ocr = RapidOCR()
                logging.info("OCR model initialized successfully")

            stage = "Chụp vùng màn hình đã chọn"
            region = self.region
            if region is None or region.width() < 10 or region.height() < 10:
                raise ValueError("Vùng nhận diện không hợp lệ. Hãy nhấn F7 và chọn lại vùng chữ.")

            box = {
                "left": region.x(),
                "top": region.y(),
                "width": region.width(),
                "height": region.height(),
            }
            with mss.mss() as screen_capture:
                shot = screen_capture.grab(box)
                image = Image.frombytes("RGB", shot.size, shot.rgb)

            stage = "Nhận diện chữ bằng OCR"
            result, _ = self.ocr(np.array(image))
            lines = []
            if result:
                for item in result:
                    if len(item) >= 2 and item[1]:
                        clean = item[1].strip()
                        if clean:
                            lines.append(clean)

            source_text = " ".join(lines).strip()
            if not source_text or len(source_text) <= 1:
                self.candidate_source = ""
                self.candidate_count = 0
                self.signals.info.emit("● ĐANG QUÉT • CHƯA THẤY CHỮ")
                return

            source_key = self.normalize_source(source_text)
            if source_key != self.candidate_source:
                self.candidate_source = source_key
                self.candidate_count = 1
                self.signals.info.emit("● ĐANG QUÉT • CHỜ CHỮ ỔN ĐỊNH")
                return

            self.candidate_count += 1
            if self.candidate_count < 2:
                return

            if source_key == self.last_source_key:
                return

            cached_translation = self.translation_cache.get(source_key)
            if cached_translation:
                self.last_source = source_text
                self.last_source_key = source_key
                self.signals.result.emit(source_text, cached_translation)
                return

            self.refresh_daily_counter()
            if self.daily_request_count >= self.daily_request_limit:
                raise RuntimeError(
                    f"Đã đạt giới hạn an toàn {self.daily_request_limit} lượt dịch/ngày. "
                    "Bộ đếm sẽ tự đặt lại vào ngày mai; các câu đã dịch vẫn dùng được từ bộ nhớ đệm."
                )

            now = time.time()
            elapsed = now - self.last_request_at
            if elapsed < self.min_request_interval:
                remaining = max(1, int(self.min_request_interval - elapsed))
                self.signals.info.emit(f"● ĐỢI {remaining} GIÂY • CHỐNG GIỚI HẠN DỊCH")
                return

            stage = "Dịch tiếng Anh sang tiếng Việt qua Internet"
            # Persist the request time/count before calling the remote service.
            self.last_request_at = now
            self.daily_request_count += 1
            self.save_state()

            translated = self.translator.translate(source_text)
            if not translated:
                raise RuntimeError("Google Translate không trả về bản dịch.")

            self.translation_cache[source_key] = translated
            if len(self.translation_cache) > 500:
                self.translation_cache = dict(list(self.translation_cache.items())[-500:])

            self.last_source = source_text
            self.last_source_key = source_key
            self.error_retry_after = 0.0
            self.save_state()
            logging.info("Translated OCR text successfully: %s", source_text[:180])
            self.signals.result.emit(source_text, translated)
        except Exception as error:
            raw_error = str(error)
            detail = f"{stage}: {type(error).__name__}: {raw_error}"
            logging.exception("Processing failed at stage: %s", stage)
            if "TooManyRequests" in raw_error or "too many requests" in raw_error.lower():
                self.error_retry_after = time.monotonic() + 300.0
                detail += " | Google đang giới hạn lượt dịch. Ứng dụng sẽ tạm dừng gọi dịch trong 5 phút."
            elif "Đã đạt giới hạn an toàn" in raw_error:
                self.error_retry_after = time.monotonic() + 300.0
            else:
                self.error_retry_after = time.monotonic() + 8.0
            self.signals.error.emit(detail)
        finally:
            self.busy = False

    def show_translation(self, source, translated):
        self.original.setText("EN  " + source)
        self.translation.setStyleSheet(
            "color:#ffffff;font-size:19px;font-weight:700;"
        )
        self.translation.setToolTip("")
        self.translation.setText("VI  " + translated)
        self.history.append((source, translated))
        self.status.setText("● ĐÃ DỊCH")
        self.status.setStyleSheet(
            "color:#55efb0;font-size:10px;font-weight:700;"
        )

    def show_error(self, error):
        self.status.setText("● CÓ LỖI — XEM CHI TIẾT")
        self.status.setStyleSheet(
            "color:#ff7979;font-size:10px;font-weight:700;"
        )
        self.original.setText("EN  Chương trình đã dừng ở bước xử lý có lỗi")
        self.translation.setStyleSheet(
            "color:#ffb0b0;font-size:13px;font-weight:700;"
        )
        self.translation.setText("LỖI CỤ THỂ: " + error[:320])
        self.translation.setToolTip(
            error + "\n\nNhật ký đầy đủ: " + str(LOG_PATH)
        )

    def set_scan_status(self, status):
        self.status.setText(status)
        self.status.setStyleSheet(
            "color:#55efb0;font-size:10px;font-weight:700;"
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    hud = Hud()
    screen = app.primaryScreen().availableGeometry()
    hud.move(
        screen.x() + 40,
        screen.y() + screen.height() - hud.height() - 70
    )
    hud.show()

    QMessageBox.information(
        hud,
        APP_NAME,
        "CÁCH SỬ DỤNG\n\n"
        "1. Mở Roblox ở chế độ Windowed hoặc Borderless.\n"
        "2. Nhấn F7 hoặc Chọn vùng, kéo quanh hội thoại/phụ đề.\n"
        "3. Phần mềm tự quét và dịch Anh → Việt.\n\n"
        "F6: Tạm dừng / tiếp tục\n"
        "F7: Chọn lại vùng\n"
        "F8: Ẩn / hiện HUD\n"
        "F9: Xóa nội dung\n\n"
        "Dùng biểu tượng R ở khay hệ thống để mở HUD lại khi đã ẩn.\n"
        "Dịch trực tuyến cần Internet."
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
