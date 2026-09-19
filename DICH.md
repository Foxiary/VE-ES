# Quy trình đưa bản dịch vào game

Tài liệu này là **đường đi từ bảng dịch tới file cài được**. Chi tiết từng tool
nằm ở `tools/README.md`, chi tiết format nằm ở `CLAUDE.md`.

Hai nhánh tách rời nhau, không phụ thuộc nhau:

| | nội dung | file game | tool ghi |
|---|---|---|---|
| **Thoại** | 96.132 dòng trong 54 kịch bản | `STORY.cpk` | `applyvi.py` |
| **Giao diện** | menu, Options, từ điển, tên chương | `SYSTEM.cpk` | `applyui.py` |

---

## Nhánh thoại — `STORY.cpk`

### 1. Rút text ra bảng

```bash
python tools/mksheet.py --out work/virche_vi.xlsx
```

Đọc thẳng `STORY.cpk` + `SYSTEM.cpk` ở thư mục gốc. Ra một sheet cho mỗi file
kịch bản (`100`, `101`, …) và một sheet cho mỗi bảng trong `DATABASE/`.

Cột: `ID | Nguồn (EN) | Tiếng Việt | Tiếng Nhật | Ghi chú | kind | bytes`

**Không được đổi thứ tự cột.** Các tool đọc cột nguồn ở B và cột dịch ở C
**theo vị trí**. Cột tiếng Nhật nằm ở D chứ không cạnh cột nguồn là vì vậy.

### 2. Nạp bản dịch có sẵn

Khi nhóm dịch gửi bảng mới (bảng neo theo bản Nhật, có cột `EN ID`):

```bash
python tools/mksheet.py --merge "Shuuen_JP_STORY.xlsx" --out work/virche_vi.xlsx
```

Ghép **theo `EN ID`**, không dò nội dung. Cột `canh bao` đánh dấu dòng cần soát:

| cờ | nghĩa |
|---|---|
| `khong vua block` | câu dịch dài hơn block gốc (không còn là vấn đề, xem dưới) |
| `qua rong` | vượt bề rộng khung, đo bằng font sẽ ship |
| `markup lech` | `#NAME[1]` / `#Color[]` / `#n` khác block bị ghi đè |
| `cau Nhat lech` | câu Nhật nguồn không nằm ở vị trí đó bên bản Nhật |
| `chua dich` | chưa có bản dịch |

### 3. Ghi vào kịch bản

```bash
python tools/applyvi.py work/virche_vi.xlsx STORY.cpk work/story-vi
```

Mỗi file dựng lại đều phải qua kiểm tra mới được ghi ra đĩa — walk dừng đúng
`EXPORT_DATA`, không con trỏ lạc, **đồ thị gọi hàm và đồ thị nhảy y nguyên**.
File nào trượt thì không ghi.

Tuỳ chọn hay dùng:

```bash
--dry-run              chỉ báo cáo
--fit-width            bỏ dòng rộng hơn khung backlog
--report qua-rong.csv  xuất danh sách dòng cần rút gọn
--font dist/SYSTEM.cpk font để đo bề rộng — phải là font SẼ SHIP
```

### 4. Đóng gói và cài

```bash
python tools/cpk.py repack STORY.cpk work/STORY_vi.cpk work/story-vi
cp work/STORY_vi.cpk "$APPDATA/Ryujinx/mods/contents/01009cf01bac4000/vn-translation/romfs/STORY.cpk"
```

---

## Nhánh giao diện — `SYSTEM.cpk`

Font và text giao diện đi chung một file, nên bước đóng gói làm một lần.

```bash
python tools/glossary.py --out work/glossary.xlsx     # rút riêng màn Glossary
python tools/applyui.py work/glossary.xlsx work/out   # ghi vào .gbin/.gstr
python build.py                                        # font + text -> dist/SYSTEM.cpk
cp dist/SYSTEM.cpk "$APPDATA/Ryujinx/mods/contents/01009cf01bac4000/vn-translation/romfs/SYSTEM.cpk"
```

Text giao diện đi qua `gbnl.py` nên **dài bao nhiêu cũng được** — nó dựng lại
toàn bộ string pool và ánh xạ lại offset.

---

## Kiểm tra sau khi cài

Đọc ngược từ đúng file trong thư mục mod, không tin file trong `work/`:

```python
from cpk import CPK
from stcm2l import Script
c = CPK(r'%APPDATA%/Ryujinx/mods/.../STORY.cpk')
for _i, name, row in c.files():
    if not name.endswith('.DAT'):
        continue
    s = Script(c.read(row))
    assert s.check()[0] and s.check()[1] == 0
    assert s.check_calls() == 0 and s.check_pointers() == 0
```

**Kiểm tra cấu trúc sạch không có nghĩa là game chạy.** Ba lần liên tiếp bản
vá qua hết kiểm tra mà vẫn treo hoặc đen màn. Thứ tìm ra nguyên nhân là bản
tái hiện tối giản — chênh bản gốc **đúng 8 byte và một dòng** — vì diff nhỏ tới
mức đọc hết được bằng mắt.

---

## Những giới hạn đã đo, và những giới hạn không có thật

**Không có giới hạn byte.** Dò bằng dòng 100 → 800 byte, game chạy hết. Con số
84 byte ghi trong tài liệu cũ chỉ là chỗ text tiếng Anh gốc dừng lại.

**Đổi kích thước block không làm treo game.** Ghi chú cũ trong `portjp2us.py`
mô tả đúng triệu chứng nhưng sai nguyên nhân: thủ phạm là ba trường địa chỉ
tuyệt đối `stcm2l.build()` chép nguyên si (xem `CLAUDE.md`).

**Thứ thật sự giới hạn là bề rộng khung**, đo bằng `textwidth.py`:

```
màn kể chuyện  ~3200      khung thoại  ~2990      backlog  ~2430
```

Thiết kế theo **backlog** vì mọi câu thoại đều được chiếu lại ở đó.

**Đo bề rộng bằng font sẽ ship, không phải font gốc.** Hai bộ có metric khác
nhau tới 15% và sai cả thứ tự giữa các font.

---

## Lùi lại khi hỏng

Giữ bản chạy được trước mỗi lần cài:

```bash
cp "$APPDATA/Ryujinx/.../STORY.cpk" work/STORY_vi_prev.cpk
```

Gỡ hẳn mod để so với bản gốc — dời cả thư mục ra ngoài cây `mods/contents/`,
cùng ổ nên tức thì chứ không copy 500 MB:

```bash
mv "$APPDATA/Ryujinx/mods/contents/01009cf01bac4000/vn-translation" \
   "$APPDATA/Ryujinx/mods/_tat_tam_vn-translation"
```

Ryujinx giữ file khi game đang chạy (`Device or resource busy`) — phải đóng
game trước.

Mỗi lần dựng font tốn ~450 MB trong `work/`; dọn bản cũ thường xuyên.
