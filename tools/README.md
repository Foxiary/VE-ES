# tools/

Thư viện + script cho bản dịch Virche. Chi tiết format nằm ở `../CLAUDE.md`.

Không tool nào phụ thuộc vào Virche: đưa `.ffu` / `.cpk` của game Otomate khác
vào là chạy. Thứ duy nhất gắn với game này là `translate_glossary.py`.

## Tool chính

### `ffugen.py` — sinh `.ffu` từ OTF/TTF

```bash
python ffugen.py --template stock.ffu --out new.ffu --font "path/to.ttf"
python ffugen.py --template stock.ffu --out new.ffu \
    --font "latin.ttf" --font "cjk.otf#0"        # chuỗi fallback
```

Cỡ chữ **tự dò** cho khớp chiều cao chữ hoa của template — đừng chỉ định `--px`
trừ khi có lý do, vì kanji giữ từ template nên Latin lệch cỡ là lộ ngay.

`--font` lặp được nhiều lần theo thứ tự ưu tiên. Ký tự không font nào có sẽ
**giữ nguyên bitmap gốc** từ template, nên dùng font chỉ có Latin vẫn được:
kanji giữ hình gốc của game.

Tham số hay dùng: `--pad` (đệm trên/dưới, tăng nếu dấu sát mép), `--match-char`
(ký tự dùng để dò cỡ, mặc định `A`), `--no-vn` (không thêm charset tiếng Việt).

### `cpk.py` — bung / đóng gói `.cpk`

```bash
python cpk.py list   SYSTEM.cpk
python cpk.py unpack SYSTEM.cpk font out_dir      # lọc theo chuỗi trong đường dẫn
python cpk.py repack SYSTEM.cpk SYSTEM_vn.cpk replacement_dir
```

Khi repack, file trùng tên trong `replacement_dir` được thay và ghi **không
nén**; file khác chép nguyên dạng đã nén.

### `gbnl.py` — đọc / dựng lại `.gbin` và `.gstr`

```bash
python gbnl.py file.gbin      # in schema + kiểm tra round-trip
```

Dùng cái này khi chuỗi tiếng Việt **dài hơn** bản gốc — nó dựng lại string pool
và ánh xạ lại toàn bộ offset. Chạy không tham số sẽ báo round-trip có
`BIT-IDENTICAL` không; **luôn kiểm tra trước khi tin tool**.

## Tool phụ

### `ffu.py` — đọc/ghi `.ffu`

```bash
python ffu.py font.ffu "Aáàả"   # in metric từng glyph
```

Cũng là thư viện: `load()`, `index()`, `bitmap()`, `to_png()`, `build()`.
`build()` giữ nguyên chiều cao ô nên chỉ hợp sửa glyph lẻ — đổi chiều cao thì
dùng `ffugen.py`.

### `patchstr.py` — sửa `.gstr` tại chỗ

Ghi đè đúng ô cũ, nên chuỗi mới phải **≤ chuỗi cũ tính theo byte UTF-8**. Nhanh
và không đụng bảng offset, nhưng tiếng Việt có dấu thường dài hơn tiếng Anh nên
phần lớn trường hợp phải dùng `gbnl.py`.

### `vnfont.py` — ghép dấu từ glyph gốc

Hướng làm **cũ**, giữ lại làm đường lui. Nó không render từ font ngoài mà cắt
dấu từ chính glyph của game rồi chồng lên thân chữ:

| dấu | nguồn |
|---|---|
| huyền, sắc, ngã, mũ | `à á ã â` và bản hoa |
| breve (`ă`) | cung đáy chữ `o` |
| nặng | chấm của `.` |
| horn (`ơ ư`) | dấu nháy cong `’` |
| hỏi | **dấu phẩy lật ngang** |

Ưu điểm là giữ 100% nét gốc; nhược điểm là dấu ghép nhìn không đẹp bằng font
dựng sẵn. `draw_hook()` bên trong chỉ là đường lui cho font không có dấu phẩy.

### `translate_glossary.py` — bản dịch mẫu

Vá vài màn để kiểm tra render: menu title, Glossary, thanh phím, và khung Sample
trong Options → Display → Font. Câu trong khung Sample cố ý gom đủ 5 dấu thanh,
mũ, breve, horn, `Đ` và `Ở` hoa (horn + hỏi — tổ hợp chật nhất), để so 4 font
chỉ bằng một màn hình.

Đây là script gắn với Virche; game khác thì viết script riêng.

## Phụ thuộc

`Pillow` (render + scale glyph), `fontTools` (đọc cmap để biết font có ký tự
nào). Chỉ `ffugen.py` cần `fontTools`.
