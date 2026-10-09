# VE-ES Desktop

Ứng dụng Electron cho bộ công cụ [VE-ES](https://github.com/Foxiary/VE-ES). Giao diện cung cấp biểu mẫu, chọn tệp, nhật ký trực tiếp và nút dừng cho 34 thao tác dòng lệnh hiện có. Bản này chứa `ffugen.py` ở commit `6f8e98d`: viền tối `--stroke`, và dấu câu tiếng Nhật (`？！。「」…`) được vẽ bằng glyph Latin của font nguồn (tắt bằng `--no-normalize-punctuation`).

Ứng dụng không chứa dữ liệu game, font, bảng dịch hoặc khóa. Khi chọn một thư mục dự án, ứng dụng chép các script, `build.py`, `fonts.json` và tài liệu nguồn còn thiếu vào đó. Tệp người dùng đã sửa được giữ nguyên.

## Chạy từ mã nguồn

1. Cài Node.js và Python 3.
2. Trong thư mục `desktop`, chạy `npm install` rồi `npm start`.
3. Trong ứng dụng, chọn **Python environment → Set up Python packages** để tạo môi trường riêng và cài Pillow, fontTools, openpyxl, NumPy. Bạn cũng có thể chọn một Python đã cài các thư viện này.
4. Chọn thư mục chứa dữ liệu dự án trong **Workspace**. Xem **Source documentation** để biết bố cục và quy trình dịch.

Nếu npm chặn bước cài Electron, chạy `npm approve-scripts electron` và `node node_modules/electron/install.js` một lần.

## Đóng gói

- macOS: `npm run dist:mac`
- Windows x64: `npm run dist:win -- --x64`
- Linux: `npm run dist:linux`

Bản phát hành trước gồm DMG cho Mac Apple Silicon, bộ cài và bản portable Windows x64. Các gói chưa được ký số; bản Windows được build trên macOS nên cần kiểm tra chạy trực tiếp trên Windows.

## Thông báo cập nhật

Khi mở ứng dụng và mỗi ngày một lần, ứng dụng kiểm tra commit mới nhất của repo VE-ES công khai. Nếu khác commit nguồn được đóng gói, ứng dụng hiển thị thông báo trong cửa sổ và, nếu hệ điều hành hỗ trợ, một thông báo desktop cho mỗi commit mới. Nút **Check updates** kiểm tra ngay. Ứng dụng không tự tải hoặc cài mã mới; cần build gói desktop mới để sử dụng mã nguồn mới. Lỗi mạng hoặc giới hạn API không cản trở công việc thông thường.

## Cách hoạt động

Mỗi thao tác chạy script Python gốc với danh sách tham số, không qua shell. Các giá trị lặp như `--font` và `--sheet` dùng mỗi dòng một giá trị. Đường dẫn tương đối được tính từ workspace đã chọn. Nhật ký hiển thị đầu ra; **Stop** dừng tiến trình đang chạy.

`build.py` dành riêng cho bố cục dự án Virche. Nhiều công cụ khác nhận dữ liệu từ game Otomate khác như tài liệu nguồn mô tả. Biểu mẫu của `translate_glossary.py` ghi rõ các bản dịch mẫu có sẵn trong repo nguồn.

Khi khởi động, ứng dụng chỉ cập nhật script và cấu hình trong workspace nếu chúng còn khớp bản nguồn được đóng gói trước đó. Tệp người dùng tự sửa được giữ nguyên. Script đã bị bỏ khỏi bản nguồn có thể còn trong workspace cũ nhưng không xuất hiện trong danh sách công cụ.

Ảnh chụp mã nguồn: [Foxiary/VE-ES commit `6f8e98d`](https://github.com/Foxiary/VE-ES/commit/6f8e98d1641f783c02cdeac5e350f42f25ff8c4c), lấy ngày 9 tháng 10 năm 2026.
