# Quy trình đưa bản dịch vào game

Tài liệu này là **đường đi từ bảng dịch tới file cài được**. Chi tiết từng tool
nằm ở `tools/README.md`, chi tiết format nằm ở `CLAUDE.md`.

Hai nhánh tách rời nhau, không phụ thuộc nhau:

| | nội dung | file game | tool ghi |
|---|---|---|---|
| **Thoại** | 103.382 dòng trong 54 kịch bản | `STORY.cpk` | `applyvi.py` |
| **Giao diện** | menu, Options, từ điển, tên chương | `SYSTEM.cpk` | `applyui.py` |
| **File thực thi** | 12 câu trích ở màn tiêu đề | `exefs/main` | `applyexe.py` |

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
python tools/mksheet.py --merge "Shuuen_JP_STORY (8).xlsx" --relink --out work/virche_vi.xlsx
```

**Luôn kèm `--relink`.** Cột `EN ID` bảng gửi về bước qua mọi ô mà bản Anh để
trống, nên mỗi lần bước qua là cả đoạn sau lệch một ô: 557 dòng trỏ sai chỗ và
10.277 dòng không có địa chỉ nào — hơn 7.000 trong số đó đã dịch xong. `--relink`
bỏ cột đó, khớp lại từ chính hai build (xem `tools/relinkjp.py`) và đưa tỉ lệ
dòng có bản dịch từ 91,6% lên **98,5%** — `applyvi.py` ghi được 102.888/103.382
dòng (99,5%). Không có cờ này thì ghép theo `EN ID` như cũ.

Cột `canh bao` đánh dấu dòng cần soát:

| cờ | nghĩa |
|---|---|
| `khong vua block` | câu dịch dài hơn block gốc (không còn là vấn đề, xem dưới) |
| `qua rong` | vượt bề rộng khung, đo bằng font sẽ ship |
| `markup lech` | `#NAME[1]` / `#Color[]` / `#n` khác block bị ghi đè |
| `cau Nhat lech` | câu Nhật nguồn không nằm ở vị trí đó bên bản Nhật |
| `chua dich` | chưa có bản dịch |

Dòng có cột `Nguon (EN)` trống và `Ghi chu` ghi `o trong - ban Nhat co dong nay`
là **ô tiếng Anh bỏ trống** — lệnh vẫn ở trong file, block rỗng. Đó là chỗ đặt
dòng "thừa" của bản Nhật, không phải lỗi rút text.

### 2b. Ghép tiêu đề chương

```bash
python tools/filltitles.py prefixes "<bang dich>" work/virche_vi.xlsx
python tools/filltitles.py fill     "<bang dich>" work/virche_vi.xlsx        --prefixes work/title_prefixes.xlsx
```

Một tiêu đề chương nằm **hai nơi**: trong `.DAT` chạy cảnh và trong
`dbFlowchart`. Bảng dịch từ ngoài gửi về chỉ có bản `dbFlowchart`, nên 448 tiêu
đề bên kịch bản không có bản dịch — 340 ô trống và 108 ô điền `...` (mất khóa
`<tiếng Nhật>@` nên `applyvi.py` từ chối).

Không phải việc dịch mới: khớp theo khóa tiếng Nhật thì **thân tiêu đề đã dịch
rồi**, chỉ khác một tiền tố chương. 41 tiền tố là toàn bộ phần còn thiếu, và
`prefixes` gợi ý sẵn những cái suy được từ chính bảng dịch (`Act`→`Màn`,
`Chapter`→`Chương`).

**Chạy sau `--merge`, trước `applyvi`.** Tiêu đề ghép ra là dữ liệu dẫn xuất:
merge lại là mất, chạy lại tool này là có.

**Excel cắt dấu cách cuối ô.** Cả 41 tiền tố gửi đi là `Act 1: ` và nhận về là
`Act 1:`. Tool lấy lại dấu cách từ bản gốc chứ không bắt ai giữ.

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
python build.py --sheet "Shuuen_JP_STORY.xlsx"        # font + text -> dist/SYSTEM.cpk
cp dist/SYSTEM.cpk "$APPDATA/Ryujinx/mods/contents/01009cf01bac4000/vn-translation/romfs/SYSTEM.cpk"
```

`--sheet` chạy `applyui.py` vào `work/out` rồi mới đóng gói. **Không bỏ cờ này
rồi trông chờ chạy `applyui.py` trước** — trước đây `build.py` gọi
`translate_glossary.py` ở bước đó, tức ghi đè bản dịch thật bằng mấy câu mẫu.
Giờ không có `--sheet` thì nó giữ nguyên `.gbin`/`.gstr` đang có và báo ra.

`build.py` truyền `cell` / `px` / `glow` / `mark_lift` trong `fonts.json` xuống
`ffugen.py`. Thiếu bước đó thì font render ra khác hẳn file đang ghi cấu hình
cho nó.

**Kiểm font bằng ảnh đã thu nhỏ 0.588, đừng kiểm ở cỡ file.** Engine vẽ font
ADV ở tỉ lệ đó, nên khe hở 1–2 hàng giữa dấu thanh và dấu mũ — thứ mọi font
Latin đều để — biến mất và chữ `ố` trông như bị cắt cụt. Ở cỡ file thì hoàn
toàn không thấy gì bất thường, và mọi phép kiểm cấu trúc đều sạch. `mark_lift`
trong `fonts.json` là thứ bù lại; xem `CLAUDE.md`.

Text giao diện đi qua `gbnl.py` nên **dài bao nhiêu cũng được** — nó dựng lại
toàn bộ string pool và ánh xạ lại offset.

---

## Nhánh file thực thi — `exefs/main`

Màn tiêu đề hiện một câu trích của ending vừa phá. **Không câu nào nằm trong
romfs** — đã quét cả 22 database trong `SYSTEM.cpk`, 117 kịch bản trong
`STORY.cpk`, `SaveUtil/`, `Shader/`; `GAME.cpk` thì chỉ có `.tid` và `.CL3`.
Cả 12 câu là chuỗi C trong `.rodata` của `exefs/main`.

```bash
python tools/exefs.py extract  "...[USA][v0].nsp" work/exefs     # can prod.keys
python tools/exefs.py segments work/exefs/main work/exefs
python tools/exefs.py sheet    work/exefs/main.rodata.bin --grep "
 
"
python tools/applyexe.py work/title_quotes.xlsx work/exefs/main work/exefs-vi/main --install
```

Ba chỗ khác hẳn hai nhánh kia:

- **Ngắt dòng là `
` thật, không phải `#n`.** Đừng cho đi qua
  `linebreak.to_game()`.
- **Ship vào `exefs/`, không phải `romfs/`** — thư mục khác, độc lập với hai
  nhánh trên. `--install` đặt đúng chỗ.
- **Câu dài hơn bản gốc vẫn được.** Các câu này được trỏ tới qua một bảng con
  trỏ 64-bit ở đầu `.rodata`, nên `applyexe.py` ghi câu dài ra vào 4.056 byte
  đệm giữa `.rodata` và `.data` rồi chỉnh con trỏ. Hết chỗ thì từ chối, không
  cắt câu.

NSO được dựng lại **không nén** (xoá bit 0–2 của cờ ở `0x0C`), và hash SHA256
của cả ba segment ở `0xA0`/`0xC0`/`0xE0` phải ghi lại — vá `.rodata` mà quên
hash thì file trông ổn và bị loại lúc nạp.

---

## Bảng dịch từ ngoài gửi về thường bị bảng tính làm hỏng

Bốn thứ đã gặp thật, tool nay tự chịu được, nhưng biết để khỏi mất thì giờ:

| triệu chứng | nguyên nhân | chỗ xử lý |
|---|---|---|
| hàng loạt dòng `van ban khong khop` | mỗi `
` bị thêm một dấu cách phía sau | `linebreak.canon()` |
| `"1"` thành `"1.0"` | Excel lưu ô một chữ số thành **số** | `applyvi.cell_str()` |
| `や　ゆ　よ` thành `や ゆ よ` | U+3000 bị đổi thành dấu cách thường | `linebreak.canon()` |
| `markup lech` hàng loạt | người dịch ngắt dòng lại | chỉ kiểm lệnh **có tham số** |

`canon()` **chỉ dùng để so sánh**. Chữ ghi vào game vẫn là chữ người dịch gõ.

Với dòng giao diện, số lượng `#n` khác bản gốc là **hợp lệ** — text `.gbin` đi
qua `gbnl.py` nên không có trần độ dài. Chỉ `#NAME[]`, `#Color[]`, `#PosX[]`
mới bắt buộc giữ nguyên. Với dòng thoại thì không nới, vì đó là trần khác.

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
