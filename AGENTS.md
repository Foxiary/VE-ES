# VIRCHE EVERMORE — bản dịch tiếng Việt (Switch, title 01009CF01BAC4000)

Repo này **không chứa nội dung game**. Nó chứa công cụ sinh font và vá text;
asset game nằm cùng thư mục nhưng bị `.gitignore` loại ra.

Điểm khác biệt so với một bản dịch thông thường: mục tiêu chính là
`tools/ffugen.py` — **generator OTF/TTF → `.ffu`**. Format `.ffu` dùng chung
cho nhiều game Otomate / Idea Factory, nên viết một lần rồi đổi `--template`
là dùng lại được cho game khác.

## Bố cục

```
SYSTEM.cpk, GAME.cpk, …      romfs game đã bung (gitignored)
Font/                        font nguồn tải từ Google Fonts (gitignored, xem Font/README.md)
fonts.json                   font nào render file .ffu nào
build.py                     một lệnh: bung → render → vá text → đóng gói → cài
DICH.md                      quy trình đưa bản dịch vào game
tools/                       thư viện + script, xem tools/README.md
work/                        trung gian (gitignored): work/stock là template bung từ CPK
dist/                        SYSTEM.cpk đã build (gitignored, ~460 MB)
```

## Build

```bash
python build.py              # ra dist/SYSTEM.cpk
python build.py --install    # và copy luôn vào thư mục mods của Ryujinx
python build.py --fonts-only # chỉ dựng lại font, bỏ qua bước text
python build.py --clean      # bỏ cache work/stock rồi bung lại
```

Lần đầu chạy sẽ bung template `.ffu` từ `SYSTEM.cpk` vào `work/stock/` — mất
vài phút vì phải giải nén CRILAYLA bằng Python. Các lần sau dùng cache.

## Cài vào Ryujinx

```
%APPDATA%\Ryujinx\mods\contents\01009cf01bac4000\vn-translation\romfs\SYSTEM.cpk
```

`build.py --install` tự copy vào đúng chỗ này. Khác dự án UNLOGICAL ở chỗ mod
là **một file CPK** chứ không phải cây thư mục, nên không dùng junction được —
mỗi lần build là phải copy đè.

## Quy tắc

**Comment trong code viết bằng tiếng Anh.** Tài liệu (`AGENTS.md`, README) thì
tiếng Việt; `CLAUDE.md` tiếng Anh vì nó là tài liệu format.

**Đổi chiều cao ô glyph thì phải sửa header.** Trường `0x0A` và `0x0E` trong
`.ffu` mang chiều cao ô ở byte thấp. Ghi glyph cao hơn mà để nguyên hai trường
này là **game văng**. `ffugen.py` tự lo, nhưng sửa tay thì phải nhớ.

**Đụng `.gstr` / `.gbin` thì kiểm tra round-trip trước.** Dựng lại file mà
không đổi gì phải ra **bit-identical**:

```bash
python tools/gbnl.py work/stock/dbDictionary.gbin
```

Giữa bảng record và string pool có một khối schema; ghi đè nó bằng `00` sẽ làm
văng game ngay khi mở màn hình dùng bảng đó. Đây chính là lỗi đã làm văng màn
Special Scenario.

**Font phải đủ 146 ký tự tiếng Việt.** Không font hệ thống Windows nào vừa đủ
tiếng Việt vừa có kanji — `ffugen.py` xử lý bằng cách giữ nguyên bitmap kanji
từ template. Muốn đồng bộ cả kanji thì cần font CJK có tiếng Việt.

## Trạng thái

- **Thoại đã vá xong**: 94.641/96.132 dòng trong `STORY.cpk`, chạy được trên
  Ryujinx. Quy trình ở `DICH.md`.
- Font: 5 file sinh từ Newsreader / Tinos / Source Serif 4 / Open Sans
  (bảng ở `Font/README.md`). Chiều cao ô **phải bằng
  template** — engine co glyph theo tỉ lệ `88/cell`, để ô phình ra cho vừa dấu
  thanh là chữ nhỏ đi 19%.
- Còn lại: 851 dòng lệch markup, 531 chưa dịch, 109 tên chương mất khoá, và
  ~59 dòng rộng quá khung backlog cần rút gọn.
