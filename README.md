# RobRun Translator HUD

Ứng dụng Windows dạng HUD nổi: bạn chọn một vùng hội thoại/phụ đề trên màn hình Roblox, ứng dụng OCR chữ trong vùng đó và dịch tiếng Anh sang tiếng Việt.

## Tải EXE từ GitHub Actions

Mỗi lần có commit lên nhánh `main`, GitHub Actions sẽ tự biên dịch ứng dụng trên máy Windows:

1. Mở tab **Actions** của repository.
2. Chọn workflow **Build Windows EXE**.
3. Mở lần chạy mới nhất có trạng thái **Success**.
4. Ở cuối trang, phần **Artifacts**, tải `RobRunTranslatorHUD-Windows`.
5. Giải nén ZIP và chạy `RobRunTranslatorHUD.exe`.

Khi tạo tag phiên bản dạng `v1.0.0`, workflow còn tự tạo GitHub Release kèm EXE.

## Sử dụng

1. Mở Roblox ở chế độ **Windowed** hoặc **Borderless** (không dùng Exclusive Fullscreen).
2. Chạy `RobRunTranslatorHUD.exe`.
3. Nhấn **F7** hoặc nút **Chọn vùng**, kéo quanh vùng hội thoại/phụ đề.
4. HUD quét vùng đã chọn khoảng mỗi 0,8 giây và hiển thị bản dịch tiếng Việt.
5. Kéo phần nền HUD để di chuyển cửa sổ. Nút dấu gạch ngang sẽ ẩn HUD; mở lại bằng biểu tượng R ở khay hệ thống.

## Phím tắt toàn hệ thống

- **F6**: Tạm dừng / tiếp tục quét.
- **F7**: Chọn lại vùng nhận diện.
- **F8**: Ẩn / hiện HUD.
- **F9**: Xóa nội dung hiện tại.

## Chống giới hạn dịch

- Chỉ gửi dịch khi OCR đọc được cùng một nội dung trong ít nhất 2 lần quét liên tiếp.
- Khoảng cách tối thiểu giữa hai yêu cầu Google Translate là 6 giây.
- Lưu bộ nhớ đệm tối đa 500 câu đã dịch vào máy để không gửi lại câu cũ.
- Giới hạn an toàn 160 yêu cầu dịch mỗi ngày trên máy này; bộ đếm tự đặt lại theo ngày.
- Khi Google trả lỗi TooManyRequests, ứng dụng tạm ngừng gọi dịch 5 phút.
- OCR quét mỗi 1,4 giây; việc đọc chữ vẫn chạy cục bộ.

Dữ liệu bộ nhớ đệm và bộ đếm được lưu tại `%LOCALAPPDATA%\\RobRunTranslatorHUD\\state.json`.

## Công nghệ và quyền riêng tư

- OCR chạy cục bộ trên máy.
- Bản dịch hiện dùng Google Translate qua thư viện `deep-translator`, cần Internet.
- Nội dung OCR trong vùng đã chọn được gửi tới dịch vụ Google Translate để dịch.
- Ứng dụng chỉ chụp vùng màn hình do người dùng chọn; không inject, hook, đọc bộ nhớ hay sửa tệp Roblox.

## Lưu ý

- Nên chọn vùng nhỏ, chỉ bao gồm hội thoại/phụ đề để OCR nhanh và chính xác hơn.
- Lần đầu chạy có thể cần thời gian khởi tạo mô hình OCR.
- Overlay có thể không nổi trên game chạy bằng Exclusive Fullscreen; hãy chuyển sang Windowed/Borderless.
- Phím F6–F9 là phím tắt toàn hệ thống; chúng có thể trùng với chức năng phím của game khác.
- Đây là bản MVP: chưa có tự động dò khung hội thoại, dịch offline hoặc lịch sử lưu ra file.

## Build thủ công trên Windows

Cài Python 3.11, sau đó chạy `BUILD_EXE.bat`. File EXE sẽ nằm trong `dist/`.
